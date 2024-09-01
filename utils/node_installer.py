import random
import shutil
import subprocess
import sys
import os
import platform
import time
import urllib
from urllib.parse import urlparse
import zipfile

import git
from git import RemoteProgress
from tqdm import tqdm
from .common import find_git_root


def get_node_installer():
    from .file_downloader import FileDownloader

    file_downloader = FileDownloader().download_file
    return NodeInstaller(file_downloader)


# NOTE: this code is taken from comfy manager and is modified to support cloning of specific commits
class NodeInstaller:
    def __init__(self, file_downloader):
        comfy_runner_dir = find_git_root(
            os.path.dirname(__file__)
        )  # NOTE: this assumes ComfyUI is always next to comfy_runner
        self.comfy_path = os.path.join(os.path.dirname(comfy_runner_dir), "ComfyUI")
        self.comfyui_manager_path = os.path.abspath(
            os.path.join(self.comfy_path, "custom_nodes", "ComfyUI-Manager")
        )
        self.custom_nodes_path = os.path.abspath(
            os.path.join(self.comfyui_manager_path, "..")
        )
        self.js_path = os.path.join(self.comfy_path, "web", "extensions")
        self.git_script_path = os.path.join(self.comfyui_manager_path, "git_helper.py")
        self.startup_script_path = os.path.join(
            self.comfyui_manager_path, "startup-scripts"
        )
        self.download_url = file_downloader

    # ----------- helper utils ----------------
    def _is_valid_url(self, url):
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except ValueError:
            return False

    def _run_script(self, cmd, cwd="."):
        if len(cmd) > 0 and cmd[0].startswith("#"):
            print(f"[ComfyUI-Manager] Unexpected behavior: `{cmd}`")
            return 0

        subprocess.check_call(cmd, cwd=cwd)

        return 0

    # not really in use
    def _remap_pip_package(self, pkg):
        pip_overrides = {}  # e.g. {"imageio[ffmpeg]": "imageio",}
        if pkg in pip_overrides:
            res = pip_overrides[pkg]
            print(f"[ComfyUI-Manager] '{pkg}' is remapped to '{res}'")
            return res
        else:
            return pkg

    def _execute_install_script(self, url, repo_path):
        install_script_path = os.path.join(repo_path, "install.py")
        requirements_path = os.path.join(repo_path, "requirements.txt")

        if os.path.exists(requirements_path):
            print("Install: pip packages")
            with open(requirements_path, "r") as requirements_file:
                for line in requirements_file:
                    package_name = self._remap_pip_package(line.strip())
                    if package_name and not package_name.startswith("#"):
                        install_cmd = [
                            sys.executable,
                            "-m",
                            "pip",
                            "install",
                            package_name,
                        ]
                        if package_name.strip() != "" and not package_name.startswith(
                            "#"
                        ):
                            try:
                                self._run_script(install_cmd, cwd=repo_path)
                            except Exception as e:
                                print(f"error installing {url} ")
                                return False

        if os.path.exists(install_script_path):
            print(f"Install: install script")
            install_cmd = [sys.executable, "install.py"]
            try:
                self._run_script(install_cmd, cwd=repo_path)
            except Exception as e:
                print(f"error installing {url} ")
                return False

        return True

    def _gitclone(self, custom_nodes_path, url, target_hash=None):
        repo_name = os.path.splitext(os.path.basename(url))[0]
        repo_path = os.path.join(custom_nodes_path, repo_name)

        max_retries = 5
        for attempt in range(max_retries):
            try:
                if os.path.exists(repo_path):
                    shutil.rmtree(repo_path)
                
                repo = git.Repo.clone_from(
                    url,
                    repo_path,
                    recursive=True,
                    progress=GitProgress(),
                )

                if target_hash is not None:
                    print(f"CHECKOUT: {repo_name} [{target_hash}]")
                    repo.git.checkout(target_hash)

                repo.git.clear_cache()
                repo.close()
                print(f"Successfully cloned {repo_name}")
                return True
            
            except Exception as e:
                print(f"An unexpected error occurred while cloning {repo_name}: {str(e)}")
                if attempt < max_retries - 1:
                    delay = 0.5
                    print(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    print(f"Failed to clone {repo_name} after {max_retries} attempts")
        
        return False

    def _unzip_install(self, files):
        # simply downloads the url and extracts it
        temp_filename = "manager-temp.zip"
        for url in files:
            if url.endswith("/"):
                url = url[:-1]
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
                }

                req = urllib.request.Request(url, headers=headers)
                response = urllib.request.urlopen(req)
                data = response.read()

                with open(temp_filename, "wb") as f:
                    f.write(data)

                with zipfile.ZipFile(temp_filename, "r") as zip_ref:
                    zip_ref.extractall(self.custom_nodes_path)

                os.remove(temp_filename)
            except Exception as e:
                print(f"Install(unzip) error: {url} / {e}")
                return False

        print("Installation was successful.")
        return True

    def _copy_install(self, files, js_path_name=None):
        for url in files:
            if url.endswith("/"):
                url = url[:-1]
            try:
                if url.endswith(".py"):
                    self.download_url(url, self.custom_nodes_path)
                else:
                    path = (
                        os.path.join(self.js_path, js_path_name)
                        if js_path_name is not None
                        else self.js_path
                    )
                    if not os.path.exists(path):
                        os.makedirs(path)
                    self.download_url(url, path)

            except Exception as e:
                print(f"Install(copy) error: {url} / {e}")
                return False

        print("Installation was successful.")
        return True

    def _gitclone_install(self, files, commit_hash_list=[]):
        print(f"Install: {files}")
        for idx, url in enumerate(files):
            if not self._is_valid_url(url):
                print(f"Invalid git url: '{url}'")
                return False

            max_retries = 5
            if url.endswith("/"):
                url = url[:-1]
            
            status = True
            for attempt in range(max_retries):
                try:
                    print(f"Download: git clone '{url}'")
                    repo_name = os.path.splitext(os.path.basename(url))[0]
                    repo_path = os.path.join(self.custom_nodes_path, repo_name)

                    # Clone the repository from the remote URL
                    res = self._gitclone(
                        self.custom_nodes_path,
                        url,
                        commit_hash_list[idx] if idx < len(commit_hash_list) else None,
                    )
                    if not res:
                        status = False
                        break
                    
                    # debugging code
                    # if not random.random() <= 0.5:
                    #     raise Exception("manual exception")

                    if not self._execute_install_script(url, repo_path):
                        status = False
                    
                    break
                except Exception as e:
                    print(f"Install(git-clone) error: {url} / {e}", file=sys.stderr)
                    print("***** RETRYING...")

        print("Installation was " + ("successfull" if status else "unsuccessfull"))
        return status

    # ----------- main method -----------------
    def install_node(self, json_data):
        install_type = json_data["install_type"]
        if install_type == "unzip":
            res = self._unzip_install(json_data["files"])

        if install_type == "copy":
            js_path_name = json_data["js_path"] if "js_path" in json_data else "."
            res = self._copy_install(json_data["files"], js_path_name)

        elif install_type == "git-clone":
            res = self._gitclone_install(
                json_data["files"], json_data.get("commit_hash", [])
            )

        # installing the dependencies
        if "pip" in json_data:
            for pname in json_data["pip"]:
                pkg = self._remap_pip_package(pname)
                install_cmd = [sys.executable, "-m", "pip", "install", pkg]
                try:
                    self._run_script(install_cmd, cwd=".")
                except Exception as e:
                    print(f"error installing {json_data['files'][0]} ")

        return True if res else False


# TODO: move to a separate interface
class GitProgress(RemoteProgress):
    def __init__(self):
        super().__init__()
        self.pbar = tqdm()

    def update(self, op_code, cur_count, max_count=None, message=""):
        self.pbar.total = max_count
        self.pbar.n = cur_count
        self.pbar.pos = 0
        self.pbar.refresh()
