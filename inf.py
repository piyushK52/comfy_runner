from concurrent.futures import ThreadPoolExecutor, as_completed
import glob
import importlib
import json
import os
import platform
import time
import sys
import traceback
import pkg_resources
import psutil
import subprocess
import re
import toml
import websocket
import uuid
import git
from git import Repo

from .utils.gen_status_tracker import GenerationStatusTracker

from .utils.node_installer import get_node_installer
from .constants import (
    APP_PORT,
    COMFY_BASE_PATH,
    COMFY_MODELS_BASE_PATH,
    DEBUG_LOG_ENABLED,
    MODEL_DOWNLOAD_PATH_LIST,
    MODEL_FILETYPES,
    OPTIONAL_MODELS,
    SERVER_ADDR,
    comfy_dir,
)
from .utils.comfy.api import ComfyAPI
from .utils.comfy.methods import ComfyMethod
from .utils.common import (
    clear_directory,
    convert_to_relative_path,
    copy_files,
    find_file_in_directory,
    find_process_by_port,
    is_url,
    search_file,
    update_toml_config,
)
from .utils.file_downloader import FileDownloader, FileStatus, ModelDownloader
from .utils.logger import LoggingType, app_logger


class ComfyRunner:
    def __init__(self):
        self.comfy_api = ComfyAPI(SERVER_ADDR, APP_PORT)
        self.model_downloader = ModelDownloader(MODEL_DOWNLOAD_PATH_LIST)
        self.gen_status_tracker = GenerationStatusTracker()

    # TODO: create mixins for these kind of methods
    def is_server_running(self):
        pid = find_process_by_port(APP_PORT)
        return True if pid else False

    def start_server(self):
        # checking if comfy is already running
        if not self.is_server_running():
            kwargs = {
                "shell": platform.system() == "Windows",
            }
            # TODO: remove comfyUI output from the console
            if not DEBUG_LOG_ENABLED:
                kwargs["stdout"] = subprocess.DEVNULL
                kwargs["stderr"] = subprocess.DEVNULL

            python_executable = sys.executable
            self.server_process = subprocess.Popen(
                [python_executable, "./ComfyUI/main.py", "--port", str(APP_PORT)],
                **kwargs,
            )

            # waiting for server to start accepting requests
            while not self.is_server_running():
                time.sleep(0.5)

            app_logger.log(LoggingType.DEBUG, "comfy server is running")
        else:
            try:
                if not self.comfy_api.health_check():
                    raise Exception(f"Port {APP_PORT} blocked")
                else:
                    app_logger.log(LoggingType.DEBUG, "Server already running")
            except Exception as e:
                raise Exception(f"Port {APP_PORT} blocked")

    def stop_server(self):
        pid = find_process_by_port(APP_PORT)
        if pid:
            process = psutil.Process(pid)
            process.terminate()
            process.wait()

    def clear_comfy_logs(self):
        log_file_list = glob.glob("comfyui*.log")
        for file in log_file_list:
            if os.path.exists(file):
                os.remove(file)

    def get_output(self, ws, prompt, client_id, output_node_ids):
        prompt_id = self.comfy_api.queue_prompt(prompt, client_id)["prompt_id"]

        # waiting for the execution to finish
        while True:
            out = ws.recv()
            if isinstance(out, str):
                message = json.loads(out)
                if message["type"] == "executing":
                    data = message["data"]
                    if data["node"] is None and data["prompt_id"] == prompt_id:
                        break  # Execution is done
            else:
                continue  # previews are binary data

        # fetching results
        history = self.comfy_api.get_history(prompt_id)[prompt_id]
        output_list = {"file_list": [], "text_output": []}
        output_node_ids = [str(id) for id in output_node_ids] if output_node_ids else []
        for node_id in history["outputs"]:
            if (
                output_node_ids and len(output_node_ids) and node_id in output_node_ids
            ) or not output_node_ids:
                node_output = history["outputs"][node_id]
                if "gifs" in node_output:
                    for gif in node_output["gifs"]:
                        output_list["file_list"].append(gif["filename"])

                if "text" in node_output:
                    for txt in node_output["text"]:
                        output_list["text_output"].append(txt)

                if "images" in node_output:
                    for img in node_output["images"]:
                        output_list["file_list"].append(img["filename"])

        return output_list

    def filter_missing_node(self, workflow):
        mappings = self.comfy_api.get_node_mapping_list()
        custom_node_list = self.comfy_api.get_all_custom_node_list()
        data = custom_node_list["custom_nodes"]

        # Build regex->url map
        regex_to_url = [
            {"regex": re.compile(item["nodename_pattern"]), "url": item["files"][0]}
            for item in data
            if item.get("nodename_pattern")
        ]

        # Build name->url map
        name_to_url = {
            name: url for url, names in mappings.items() for name in names[0]
        }

        registered_nodes = self.comfy_api.get_registered_nodes()

        missing_nodes = set()
        nodes = [node for _, node in workflow.items()]

        for node in nodes:
            node_type = node.get("class_type", "")
            if node_type.startswith("workflow/"):
                continue

            if node_type not in registered_nodes:
                url = name_to_url.get(node_type.strip(), "")
                if url:
                    missing_nodes.add(url)
                else:
                    for regex_item in regex_to_url:
                        if regex_item["regex"].search(node_type):
                            missing_nodes.add(regex_item["url"])

        unresolved_nodes = []  # not yet implemented in comfy

        for node_type in unresolved_nodes:
            url = name_to_url.get(node_type, "")
            if url:
                missing_nodes.add(url)

        ans = [
            node
            for node in data
            if any(file in missing_nodes for file in node.get("files", []))
        ]
        # print("********* missing nodes found: ", ans)
        return ans

    def download_models(
        self,
        workflow,
        extra_models_list,
        ignore_model_list=[],
        client_id=None,
    ) -> dict:
        models_downloaded = False
        self.model_downloader.load_comfy_models()
        models_to_download = []

        for node in workflow:
            if "inputs" in workflow[node]:
                for input in workflow[node]["inputs"].values():
                    if (
                        isinstance(input, str)
                        and any(input.endswith(ft) for ft in MODEL_FILETYPES)
                        and not any(input.endswith(m) for m in OPTIONAL_MODELS)
                    ):
                        models_to_download.append(input)

        # filtering ignored models
        m_l = []
        ignored_models_found = []
        ignored_model_names_map = {m["filename"]: m for m in ignore_model_list}
        for m in models_to_download:
            if m in ignored_model_names_map:
                ignored_models_found.append(ignored_model_names_map[m])
            else:
                m_l.append(m)
        models_to_download = m_l

        models_not_found = []
        for m in ignored_models_found:
            model_path = (
                convert_to_relative_path(m["filepath"], COMFY_MODELS_BASE_PATH)
                if "filepath" in m
                else None
            )
            if model_path and not os.path.exists(model_path):
                models_not_found.append({"model": m["filename"], "similar_models": []})
            else:
                app_logger.log(LoggingType.DEBUG, f"Ignoring model {m['filename']}")

        m_l = []
        for model in models_to_download:
            _, model = os.path.split(model)
            _, _, base_path = self.model_downloader.get_model_details(model)
            base_path = os.path.basename(base_path) if base_path else None
            if not search_file(
                model,
                COMFY_MODELS_BASE_PATH,
                parent_folder=base_path,
            ):
                m_l.append(model)
        models_to_download = m_l

        for model in models_to_download:
            if self.gen_status_tracker.is_generation_cancelled(client_id):
                break

            status, similar_models, file_status = self.model_downloader.download_model(
                model
            )
            if not status:
                models_not_found.append(
                    {
                        "model": model,
                        "similar_models": similar_models,
                    }
                )
            elif file_status == FileStatus.NEW_DOWNLOAD.value:
                models_downloaded = True

        # downloading extra models
        for model in extra_models_list:
            if self.gen_status_tracker.is_generation_cancelled(client_id):
                break

            status, file_status = self.model_downloader.download_file(
                model["filename"],
                model["url"],
                model["dest"],
            )

            if status:
                models_downloaded = (
                    True if file_status == FileStatus.NEW_DOWNLOAD.value else False
                )
                for m in models_not_found:
                    if m["model"] == model["filename"]:
                        models_not_found.remove(m)
                        break

        # checking if models_not_found are already inside comfy
        for model in models_not_found:
            if search_file(model["model"].split("/")[-1], COMFY_BASE_PATH):
                models_not_found.remove(model)

        return {
            "data": {
                "models_not_found": models_not_found,
                "models_downloaded": models_downloaded,
            },
            "message": "model(s) not found" if len(models_not_found) else "",
            "status": False if len(models_not_found) else True,
        }

    def download_custom_nodes(
        self,
        workflow,
        extra_node_urls,
        client_id=None,
    ) -> dict:
        nodes_installed = False

        # installing missing nodes
        missing_nodes = self.filter_missing_node(workflow)
        if len(missing_nodes):
            app_logger.log(
                LoggingType.INFO, f"Installing {len(missing_nodes)} custom nodes"
            )

        provided_node_url_dict = {node["url"]: node for node in extra_node_urls}
        extra_node_url_dict = {}

        for node in missing_nodes:
            if node["files"][0] in provided_node_url_dict and provided_node_url_dict[
                node["files"][0]
            ].get("commit_hash", None):
                extra_node_url_dict[node["files"][0]] = provided_node_url_dict[
                    node["files"][0]
                ]
                continue

            if self.gen_status_tracker.is_generation_cancelled(client_id):
                break

            app_logger.log(LoggingType.DEBUG, f"Installing {node['title']}")
            if node["installed"] in ["False", False]:
                nodes_installed = True
                status = self.comfy_api.install_custom_node(node)
                if status != {}:
                    app_logger.log(
                        LoggingType.ERROR,
                        "Failed to install custom node ",
                        node["title"],
                    )

        # installing custom git repos
        nodes_to_install_with_commit_hash = []
        nodes_to_install = []
        if len(extra_node_url_dict.keys()):
            custom_node_list = self.comfy_api.get_all_custom_node_list()
            custom_node_list = custom_node_list["custom_nodes"]
            url_node_map = {}
            for node in custom_node_list:
                if node["reference"] not in url_node_map:
                    url_node_map[node["reference"]] = [node]
                else:
                    url_node_map[node["reference"]].append(node)

            for git_url, node_info in extra_node_url_dict.items():

                if node_info.get("commit_hash", None):
                    nodes_to_install_with_commit_hash.append(node_info)
                elif git_url in url_node_map:
                    for node in url_node_map[git_url]:
                        nodes_to_install.append(node)
                else:
                    node = {
                        "author": "",
                        "title": "",
                        "reference": git_url,
                        "files": [git_url],
                        "install_type": "git-clone",
                        "description": "",
                        "installed": "False",
                    }
                    nodes_to_install.append(node)

            for n in nodes_to_install:
                if self.gen_status_tracker.is_generation_cancelled(client_id):
                    break

                nodes_installed = True
                app_logger.log(LoggingType.DEBUG, f"Installing {n['reference']}")
                status = self.comfy_api.install_custom_node(n)
                if status != {}:
                    app_logger.log(
                        LoggingType.ERROR, "Failed to install custom node ", n["title"]
                    )

            custom_node_installer = get_node_installer()
            for n in nodes_to_install_with_commit_hash:
                if self.gen_status_tracker.is_generation_cancelled(client_id):
                    break

                app_logger.log(LoggingType.DEBUG, f"Installing {n['title']}")
                nodes_installed = True
                json_data = {
                    "files": [n["url"]],
                    "install_type": "git-clone",
                    "commit_hash": [n["commit_hash"]],
                }
                status = custom_node_installer.install_node(json_data)
                if not status:
                    app_logger.log(
                        LoggingType.ERROR, "Failed to install custom node ", n["title"]
                    )

        return {
            "data": {"nodes_installed": nodes_installed},
            "message": "",
            "status": True,
        }

    def load_workflow(self, workflow_input):
        if os.path.exists(workflow_input):
            try:
                with open(workflow_input, "r", encoding="utf-8") as file:
                    workflow_input = json.load(file)

            except Exception as e:
                app_logger.log(LoggingType.ERROR, "Exception: ", str(e))
                return None
        else:
            workflow_input = json.loads(workflow_input)

        return workflow_input if ComfyMethod.is_api_json(workflow_input) else None

    def stop_current_generation(self, client_id=None, retry_window=3):
        """
        CAUTION: This stops any running generation on active comfyui APP_PORT (default 8188)
        client_id: tag used to identify generations
        retry_window: the amount of time (in secs) it will try to find the process (as it takes a while for comfy to start the generation)
        """
        self.gen_status_tracker.mark_generation_cancelled(client_id)
        try:
            if not client_id:
                self.comfy_api.interrupt_prompt()
            else:
                while retry_window > 0:
                    retry_gap = 1
                    current_running_gen = self.get_queue_items()
                    # exiting if unable to connect to comfy
                    if not current_running_gen:
                        retry_window = -1
                        break
                    current_running_gen = (
                        current_running_gen.get("queue_running", [])
                        if current_running_gen
                        else []
                    )
                    if len(current_running_gen):
                        info = current_running_gen[-1][-2]
                        if "client_id" in info and info["client_id"] == str(client_id):
                            self.comfy_api.interrupt_prompt()
                            app_logger.log(
                                LoggingType.INFO, "Comfy generation terminated"
                            )
                            return True

                    retry_window -= retry_gap
                    if retry_window > 0:
                        time.sleep(retry_gap)

        except Exception as e:
            app_logger.log(LoggingType.DEBUG, f"Error stopping the generation {str(e)}")
            pass

        app_logger.log(LoggingType.INFO, "Generation marked as cancelled")
        return True

    def get_queue_items(self):
        connection_attempts = 12
        for i in range(connection_attempts):
            try:
                return self.comfy_api.get_queue()
            except Exception as e:
                time.sleep(1)

        app_logger.log(
            LoggingType.ERROR, "Unable to stop generation, comfy server unreachable"
        )
        return None

    def quick_requirements_check(self, requirements_file):
        """
        this method only checks for package name and not their version.
        potential issue - if the installed pkg name is different from the requirements.txt
        then this will always return the pkg as missing
        """
        with open(requirements_file, "r") as f:
            requirements = []
            for line in f:
                if line.strip() and not line.startswith("#"):
                    delimeter = "=="
                    if ">=" in line.strip():
                        delimeter = ">="
                    elif "<=" in line.strip():
                        delimeter = "<="

                    requirements.append(line.strip().lower().split(delimeter)[0])

        missing = []
        installed_pkg_list = sorted(
            [dist.project_name.lower() for dist in pkg_resources.working_set]
        )
        for package in requirements:
            if package not in installed_pkg_list:
                missing.append(package)

        return missing

    def process_file(self, item):
        source, dest_path, filename = item
        download_file = FileDownloader().background_download
        if is_url(source):
            return download_file(source, dest_path, filename)
        else:
            return copy_files(source, dest_path, overwrite=True, filename=filename)

    def predict(
        self,
        workflow_input,
        file_path_list=[],
        extra_models_list=[],
        extra_node_urls=[],  # [{'url': github_url, 'commit_hash': xyz},...]
        stop_server_after_completion=False,
        clear_comfy_logs=True,
        output_folder="./output",
        output_node_ids=None,
        ignore_model_list=[],
        client_id=None,
        comfy_commit_hash=None,
        strict_dep_list=None,  # {numpy: 1.24.4, ...}
        checkpointing_data=None,  # { "network_data" : {"type": "Salad", "organisation": "xyz", "api-key": "xyz"}}
    ):
        """
        workflow_input:                 API json of the workflow. Can be a filepath or str
        file_path_list:                 files to copy inside the '/input' folder which are being used in the workflow
        extra_models_list:              extra models to be downloaded
        extra_node_urls:                extra nodes to be downloaded (with the option to specify commit version)
        stop_server_after_completion:   stop server as soon as inference completes (or fails)
        clear_comfy_logs:               clears the temp comfy logs after every inference
        output_folder:                  for storing inference output
        output_node_ids:                nodes to look in for the output
        ignore_model_list:              these models won't be downloaded (in cases where these are manually placed)
        client_id:                      this can be used as a tag for the generations
        comfy_commit_hash:              specific comfy commit to checkout
        strict_dep_list:                list of pkgs and their versions that can't be overrided by new nodes installation
        checkpointing_data:             config to enable sampler latent checkpointing
        """
        output_list = {}
        try:
            # TODO: add support for image and normal json files
            client_id = client_id or str(uuid.uuid4())
            workflow = self.load_workflow(workflow_input)
            if not workflow:
                app_logger.log(LoggingType.ERROR, "Invalid workflow file")
                return

            # cloning comfy repo
            comfy_repo_url = "https://github.com/comfyanonymous/ComfyUI"
            comfy_manager_url = "https://github.com/ltdrdata/ComfyUI-Manager"
            if not os.path.exists(COMFY_BASE_PATH):
                app_logger.log(LoggingType.DEBUG, "cloning comfy repo")
                comfy_repo = Repo.clone_from(comfy_repo_url, COMFY_BASE_PATH)

            if comfy_commit_hash is not None:
                try:
                    comfy_repo = Repo(COMFY_BASE_PATH)
                    current_hash = comfy_repo.rev_parse("HEAD")

                    if str(current_hash) == comfy_commit_hash:
                        # app_logger.log(
                        #     LoggingType.DEBUG,
                        #     "ComfyUI already at specified commit hash",
                        # )
                        pass
                    else:
                        app_logger.log(
                            LoggingType.DEBUG,
                            f"Attempting to move ComfyUI to commit {comfy_commit_hash}",
                        )
                        comfy_repo.remotes.origin.fetch()
                        comfy_repo.git.checkout(comfy_commit_hash)
                        app_logger.log(
                            LoggingType.DEBUG,
                            f"Successfully moved ComfyUI to commit {comfy_commit_hash}",
                        )
                except Exception as e:
                    app_logger.log(
                        LoggingType.ERROR, f"Unable to checkout ComfyUI: {str(e)}"
                    )
                    return None

            if not os.path.exists(COMFY_BASE_PATH + "custom_nodes/ComfyUI-Manager"):
                custom_manager_hash = None
                for n in extra_node_urls:
                    if n["title"] == "ComfyUI-Mananger":
                        custom_manager_hash = n["commit_hash"]
                os.chdir(COMFY_BASE_PATH + "custom_nodes/")
                manager_repo = Repo.clone_from(comfy_manager_url, "ComfyUI-Manager")
                if custom_manager_hash:
                    manager_repo.git.checkout(custom_manager_hash)
                os.chdir("../../")

            # installing requirements
            app_logger.log(
                LoggingType.DEBUG,
                "Checking comfy requirements, please wait...",
            )
            missing_pkg_list = self.quick_requirements_check(
                os.path.join(COMFY_BASE_PATH, "requirements.txt")
            )
            if missing_pkg_list and len(missing_pkg_list):
                print("missing packages: ", missing_pkg_list)
                subprocess.run(
                    ["pip", "install", "-r", COMFY_BASE_PATH + "requirements.txt"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )

            # clearing the previous logs
            if not self.is_server_running():
                self.clear_comfy_logs()

            # start the comfy server if not already running
            self.start_server()

            # enabling checkpointing
            checkpoint_node_added = False
            checkpoint_node_path = os.path.join(
                COMFY_BASE_PATH, "custom_nodes", "comfy-checkpointing"
            )
            checkpoint_config_path = os.path.join(checkpoint_node_path, "config.toml")
            if checkpointing_data:
                status = True
                if not os.path.exists(checkpoint_node_path):
                    custom_node_installer = get_node_installer()
                    json_data = {
                        "files": ["https://github.com/piyushK52/comfy-checkpointing"],
                        "install_type": "git-clone",
                    }
                    status = custom_node_installer.install_node(json_data)
                    checkpoint_node_added = status

                if not status:
                    app_logger.log(
                        LoggingType.ERROR, "Unable to enable checkpoint node"
                    )
                else:
                    if not os.path.exists(checkpoint_config_path):
                        with open(checkpoint_config_path, "w") as config_file:
                            toml.dump({}, config_file)

                    update_toml_config(checkpoint_config_path, checkpointing_data)
                    app_logger.log(LoggingType.INFO, "Checkpointing enabled")
            else:
                if os.path.exists(checkpoint_node_path) and os.path.exists(
                    checkpoint_config_path
                ):
                    update_toml_config(checkpoint_config_path, {})

            # download custom nodes
            res_custom_nodes = self.download_custom_nodes(
                workflow,
                extra_node_urls,
                client_id,
            )
            if not res_custom_nodes["status"]:
                app_logger.log(LoggingType.ERROR, res_custom_nodes["message"])
                return

            # download models if not already present
            res_models = self.download_models(
                workflow,
                extra_models_list,
                ignore_model_list,
                client_id,
            )
            if not res_models[
                "status"
            ] and not self.gen_status_tracker.is_generation_cancelled(client_id):
                app_logger.log(LoggingType.ERROR, res_models["message"])
                if len(res_models["data"]["models_not_found"]):
                    app_logger.log(
                        LoggingType.INFO,
                        "Please provide custom model urls for the models listed below or modify the workflow json to one of the alternative models listed",
                    )
                    for model in res_models["data"]["models_not_found"]:
                        print("Model: ", model["model"])
                        print("Alternatives: ")
                        if len(model["similar_models"]):
                            for alternative in model["similar_models"]:
                                print(" - ", alternative)
                        else:
                            print(" - None")
                        print("---------------------------")
                return

            # restart the server if custom nodes or models are installed
            # also check for the strict dependencies (strict_dep_list)
            if (
                res_custom_nodes["data"]["nodes_installed"]
                or res_models["data"]["models_downloaded"]
                or checkpoint_node_added
            ):
                if strict_dep_list and len(strict_dep_list):
                    for package, version in strict_dep_list.items():
                        cmd = [
                            sys.executable,
                            "-m",
                            "pip",
                            "install",
                            f"{package}=={version}",
                        ]

                        try:
                            subprocess.check_call(cmd)
                            app_logger.log(
                                LoggingType.DEBUG, f"Moved {package} to {version}"
                            )
                        except subprocess.CalledProcessError as e:
                            print(f"Failed to move {package} {version}. Error: {e}")

                app_logger.log(LoggingType.INFO, "Restarting the server")
                self.stop_server()
                self.start_server()

            if len(file_path_list):
                task_list = []
                clear_directory("./ComfyUI/input")
                for filepath in file_path_list:
                    if isinstance(filepath, str):
                        source, dest_path = filepath, "./ComfyUI/input/"
                        filename = None
                    else:
                        source, dest_path = (
                            filepath["filepath"],
                            "./ComfyUI/input/" + filepath["dest_folder"] + "/",
                        )
                        filename = filepath.get("filename", None)

                    task_list.append((source, dest_path, filename))

                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = [
                        executor.submit(self.process_file, task) for task in task_list
                    ]
                    for future in as_completed(futures):
                        try:
                            future.result()
                        except Exception as exc:
                            print(f"An error occurred: {exc}")

            # checkpoints, lora, default etc..
            comfy_directory = COMFY_MODELS_BASE_PATH + "models/"
            comfy_model_folders = [
                folder
                for folder in os.listdir(comfy_directory)
                if os.path.isdir(os.path.join(comfy_directory, folder))
            ]
            # update model paths e.g. 'v3_sd15_sparsectrl_rgb.ckpt' --> 'SD1.5/animatediff/v3_sd15_sparsectrl_rgb.ckpt'
            for node in workflow:
                if "inputs" in workflow[node]:
                    for key, input in workflow[node]["inputs"].items():
                        if (
                            isinstance(input, str)
                            and any(input.endswith(ft) for ft in MODEL_FILETYPES)
                            and not any(input.endswith(m) for m in OPTIONAL_MODELS)
                        ):
                            base = None
                            # if os.path.sep in input:
                            base, input = os.path.split(input)
                            model_path_list = find_file_in_directory(
                                comfy_directory, input
                            )
                            if len(model_path_list):
                                print(model_path_list)
                                # selecting the model_path which has the base, if neither has the base then selecting the first one or the one in the 'checkpoints' folder
                                model_path = next(
                                    (
                                        path
                                        for path in model_path_list
                                        if "checkpoints" in path
                                    ),
                                    model_path_list[0],
                                )  # preferring the "checkpoints" folder
                                if base:
                                    matching_text_seq = (
                                        ["SD1.5"]
                                        if base in ["SD1.5", "SD1.x"]
                                        else ["SDXL"]
                                    )
                                    for txt in matching_text_seq:
                                        for p in model_path_list:
                                            if txt in p:
                                                model_path = p
                                                break

                                model_path = model_path.replace(comfy_directory, "")
                                if any(
                                    model_path.startswith(folder)
                                    for folder in comfy_model_folders
                                ):
                                    model_path = model_path.split(os.path.sep, 1)[-1]
                                app_logger.log(
                                    LoggingType.DEBUG,
                                    f"Updating {input} to {model_path}",
                                )
                                workflow[node]["inputs"][key] = model_path

            # get the result
            app_logger.log(LoggingType.INFO, "Generating output please wait")
            if self.gen_status_tracker.is_generation_cancelled(client_id):
                app_logger.log(LoggingType.INFO, "Generation cancelled by the user")
                return None

            ws = websocket.WebSocket()
            host = SERVER_ADDR + ":" + str(APP_PORT)
            host = host.replace("http://", "").replace("https://", "")
            ws.connect("ws://{}/ws?clientId={}".format(host, client_id))
            node_output = self.get_output(ws, workflow, client_id, output_node_ids)
            output_list = []
            for file in node_output["file_list"]:
                path = find_file_in_directory("./ComfyUI/output", file)
                # some intermediary temp files are deleted at this point
                if path:
                    output_list.append(
                        copy_files(
                            path[0],
                            output_folder,
                            overwrite=False,
                            delete_original=True,
                        )
                    )
            # print("node output: ", node_output)
            # print("output_list: ", output_list)
            app_logger.log(
                LoggingType.DEBUG, f"output file list len: {len(output_list)}"
            )
            clear_directory("./ComfyUI/output")

            output_list = {
                "file_paths": output_list,
                "text_output": node_output["text_output"],
            }
        except Exception as e:
            app_logger.log(LoggingType.INFO, "Error generating output " + str(e))
            print(traceback.format_exc())

        # stopping the server
        if stop_server_after_completion:
            self.stop_server()

        # TODO: implement a proper way to remove the logs
        if not self.is_server_running() and clear_comfy_logs:
            self.clear_comfy_logs()

        return output_list
