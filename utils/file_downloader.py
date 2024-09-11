from enum import Enum
import os
import time
from urllib.parse import urlparse

import requests
import tarfile
import zipfile
import json
from tqdm import tqdm
from ..constants import (
    APP_PORT,
    COMFY_MODELS_BASE_PATH,
    COMFY_MODEL_PATH_LIST,
    SERVER_ADDR,
)
from .comfy.api import ComfyAPI

from .common import (
    find_git_root,
    convert_to_relative_path,
    fuzzy_text_match,
    get_default_save_path,
    get_file_size,
    search_file,
)
from .logger import LoggingType, app_logger


class FileStatus(Enum):
    NEW_DOWNLOAD = "new_download"
    ALREADY_PRESENT = "already_present"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"  # not proper


class FileDownloader:
    def __init__(self):
        pass

    def is_file_downloaded(self, filename, url, dest):
        zip_file = False
        percentage_diff = lambda a, b: int(round(abs(a - b) / b, 2) * 100)
        if url.endswith(".zip") or url.endswith(".tar"):
            # filename = filename + (".zip" if url.endswith(".zip") else ".tar")
            zip_file = True

        dest_path = f"{dest}/{filename}"
        app_logger.log(LoggingType.DEBUG, "checking file: ", dest_path)
        return os.path.exists(dest_path)
        #     downloaded_file_size = os.path.getsize(dest_path)
        #     url_file_size = get_file_size(url)
        #     # NOTE: hackish sol of checking if zip file is downloaded or not (by checking if the extracted file is approximately the same size)
        #     # possible issues 1. partially downloaded zip file 2. new model file with smaller size
        #     return downloaded_file_size == url_file_size if not zip_file else \
        #         percentage_diff(downloaded_file_size, url_file_size) <= 2
        # return False

    def background_download(self, url, dest, filename=None):
        # downloads without a progress bar + overwrites existing files (no checks performed)
        # suited for small quick downloads
        os.makedirs(dest, exist_ok=True)
        response = requests.get(url, stream=True)
        response.raise_for_status()
        filename = filename or os.path.basename(urlparse(url).path)
        filepath = os.path.join(dest, filename)
        with open(filepath, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return filepath

    def download_file(self, filename, url, dest):
        os.makedirs(dest, exist_ok=True)

        # checking if the file is already downloaded
        if self.is_file_downloaded(filename, url, dest):
            app_logger.log(LoggingType.DEBUG, f"{filename} already present")
            return True, FileStatus.ALREADY_PRESENT.value
        else:
            # deleting partial downloads
            if os.path.exists(f"{dest}/{filename}"):
                os.remove(f"{dest}/{filename}")

        max_retries = 3
        retry_delay = 3
        for _ in range(max_retries):
            try:
                # download progress bar
                app_logger.log(LoggingType.INFO, f"Downloading {filename}")
                response = requests.get(url, stream=True)
                total_size = int(response.headers.get("content-length", 0))
                progress_bar = tqdm(total=total_size, unit="B", unit_scale=True)
                with open(f"{dest}/{filename}", "wb") as handle:
                    for data in tqdm(response.iter_content(chunk_size=1024)):
                        handle.write(data)
                        progress_bar.update(len(data))

                # extract files if the downloaded file is a .zip or .tar
                if url.endswith(".zip") or url.endswith(".tar"):
                    new_filename = filename + (
                        ".zip" if url.endswith(".zip") else ".tar"
                    )
                    os.rename(f"{dest}/{filename}", f"{dest}/{new_filename}")
                    if url.endswith(".zip"):
                        with zipfile.ZipFile(f"{dest}/{new_filename}", "r") as zip_ref:
                            zip_ref.extractall(dest)
                    else:
                        with tarfile.open(f"{dest}/{new_filename}", "r") as tar_ref:
                            tar_ref.extractall(dest)
                    os.remove(f"{dest}/{new_filename}")

                return True, FileStatus.NEW_DOWNLOAD.value
            except Exception as e:
                app_logger.log(
                    LoggingType.ERROR,
                    f"Download failed: {str(e)}. Retrying in {retry_delay} seconds...",
                )
                time.sleep(retry_delay)

        app_logger.log(
            LoggingType.ERROR,
            f"Failed to download {filename} after {max_retries} attempts",
        )
        return False, FileStatus.FAILED.value


class ModelDownloader(FileDownloader):
    def __init__(self, model_weights_file_path_list, download_similar_model=False):
        super().__init__()
        self.model_download_dict = self.comfy_model_dict = {}
        self.download_similar_model = download_similar_model
        self.comfy_api = ComfyAPI(SERVER_ADDR, APP_PORT)

        # loading local data
        for model_weights_file_path in model_weights_file_path_list:
            current_dir = find_git_root(os.path.dirname(__file__))  # finding root
            file_path = os.path.abspath(
                os.path.join(current_dir, model_weights_file_path)
            )
            # print("------- opening file path: ", file_path)
            with open(file_path, "r", encoding="utf-8") as file:
                data = json.load(file)
                for model_name in data:
                    # weight files with lower index have preference
                    if model_name not in self.model_download_dict:
                        self.model_download_dict[model_name] = {
                            "url": data[model_name]["url"],
                            "dest": convert_to_relative_path(
                                data[model_name]["dest"],
                                base_comfy=COMFY_MODELS_BASE_PATH,
                            ),
                        }

    def _get_similar_models(self, model_name):
        app_logger.log(LoggingType.DEBUG, "matching model: ", model_name)
        # matching with local data
        model_list = self.model_download_dict.keys()
        similar_models = fuzzy_text_match(model_list, model_name)

        # matching with comfy data
        model_list = self.comfy_model_dict.keys()
        similar_models += fuzzy_text_match(model_list, model_name)

        return similar_models

    def load_comfy_models(self):
        self.comfy_model_dict = {}
        # these models have incorrect details in the Comfy Manager data json
        # and should be ignored here
        ignore_manager_models = ["sd_xl_base_1.0.safetensors", "sd_xl_refiner_1.0_0.9vae.safetensors"]
        for model_list_path in COMFY_MODEL_PATH_LIST:
            current_dir = find_git_root(os.path.dirname(__file__))  # finding root
            model_list_path = os.path.abspath(
                os.path.join(current_dir, model_list_path)
            )
            if not os.path.exists(model_list_path):
                app_logger.log(
                    LoggingType.DEBUG, f"model list path not found - {model_list_path}"
                )
                continue

            with open(model_list_path, "rb") as file:
                model_list = json.load(file)["models"]

            # loading comfy data
            for model in model_list:
                if model_list_path.endswith("ComfyUI-Manager/model-list.json") and model["filename"] in ignore_manager_models:     # comfy manager liser
                    continue
                
                if model["filename"] not in self.comfy_model_dict:
                    self.comfy_model_dict[model["filename"]] = [model]
                else:
                    self.comfy_model_dict[model["filename"]].append(model)

    def get_model_details(self, model_name):
        """
        If a model_name is present in the database it returns
        filename: the filename it should be downloaded as
        url:      it's download url
        dest:     where this file needs to be downloaded
        """
        if model_name in self.comfy_model_dict:
            for model in self.comfy_model_dict[model_name]:
                if model["save_path"] and model["save_path"].endswith("default"):
                    model["save_path"] = get_default_save_path(model["type"])

                return (
                    model["filename"],
                    model["url"],
                    os.path.join(COMFY_MODELS_BASE_PATH, "models", model["save_path"]),
                )

        elif model_name in self.model_download_dict:
            return (
                model_name,
                self.model_download_dict[model_name]["url"],
                convert_to_relative_path(
                    self.model_download_dict[model_name]["dest"],
                    base_comfy=COMFY_MODELS_BASE_PATH,
                ),
            )

        return None, None, None

    def download_model(self, model_name):
        # handling nomenclature like "SD1.5/pytorch_model.bin"
        base, model_name = (
            (model_name.split("/")[0], model_name.split("/")[-1])
            if "/" in model_name
            else ("", model_name)
        )
        file_status = FileStatus.NEW_DOWNLOAD.value
        filename, url, dest = self.get_model_details(model_name)

        if filename and url and dest:
            _, file_status = self.download_file(filename=filename, url=url, dest=dest)

        else:
            app_logger.log(
                LoggingType.DEBUG, f"Model {model_name} not found in model weights"
            )
            similar_models = self._get_similar_models(model_name)
            if self.download_similar_model and len(similar_models):
                pass
            else:
                return (False, similar_models, FileStatus.UNAVAILABLE.value)

        return (True, [], file_status)
