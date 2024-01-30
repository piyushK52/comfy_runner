import glob
import json
import os
import time
import psutil
import subprocess
import urllib.request
import re
import websocket
import uuid
from git import Repo
from constants import APP_PORT, DEBUG_LOG_ENABLED, MODEL_DOWNLOAD_PATH_LIST, SERVER_ADDR
from utils.comfy.api import ComfyAPI
from utils.comfy.methods import ComfyMethod
from utils.common import copy_files
from utils.file_downloader import ModelDownloader
from utils.logger import LoggingType, app_logger

class ComfyRunner:
    def __init__(self):
        self.comfy_api = ComfyAPI(SERVER_ADDR, APP_PORT)
        self.model_downloader = ModelDownloader(MODEL_DOWNLOAD_PATH_LIST)

    def is_server_running(self):
        pid = self.find_process_by_port(APP_PORT)
        return True if pid else False
            
    def start_server(self):
        # checking if comfy is already running
        if not self.is_server_running():
            command = "python ./ComfyUI/main.py"
            kwargs = {
                "shell" : True,
            }
            # TODO: remove comfyUI output from the console
            if not DEBUG_LOG_ENABLED:
                kwargs["stdout"] = subprocess.DEVNULL
                kwargs["stderr"] = subprocess.DEVNULL

            self.server_process = subprocess.Popen(command, **kwargs)

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

    def find_process_by_port(self, port):
        pid = None
        for proc in psutil.process_iter(attrs=['pid', 'name', 'connections']):
            try:
                if proc and 'connections' in proc.info and proc.info['connections']:
                    for conn in proc.info['connections']:
                        if conn.status == psutil.CONN_LISTEN and conn.laddr.port == port:
                            app_logger.log(LoggingType.DEBUG, f"Process {proc.info['pid']} (Port {port})")
                            pid = proc.info['pid']
                            break
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        
        return pid

    def stop_server(self):
        pid = self.find_process_by_port(APP_PORT)
        if pid:
            psutil.Process(pid).terminate()

    def get_output(self, ws, prompt_path, client_id, ext=None):
        with open(prompt_path, "r") as f:
            prompt = json.loads(f.read())
        prompt_id = self.comfy_api.queue_prompt(prompt, client_id)['prompt_id']
        
        # waiting for the execution to finish
        while True:
            out = ws.recv()
            if isinstance(out, str):
                message = json.loads(out)
                if message['type'] == 'executing':
                    data = message['data']
                    if data['node'] is None and data['prompt_id'] == prompt_id:
                        break #Execution is done
            else:
                continue #previews are binary data

        # fetching results (not is use rn)
        history = self.comfy_api.get_history(prompt_id)[prompt_id]
        output_list = []
        for node_id in history['outputs']:
            node_output = history['outputs'][node_id]
            if 'gifs' in node_output:
                for gif in node_output['gifs']:
                    output_list.append(gif['filename'])

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

        unresolved_nodes = []   # not yet implemented in comfy

        for node_type in unresolved_nodes:
            url = name_to_url.get(node_type, "")
            if url:
                missing_nodes.add(url)

        ans = [node for node in data if any(file in missing_nodes for file in node.get("files", []))]
        # print("********* missing nodes found: ", ans)
        return ans

    def download_models(self, workflow, extra_models_list) -> dict:
        models_downloaded = False
        self.model_downloader.load_comfy_models()
        models_to_download = []
        download_filetypes = [
            ".ckpt",
            ".safetensors",
            ".pt",
            ".pth",
            ".bin",
            ".onnx",
            ".torchscript",
        ]

        for node in workflow:
            if "inputs" in workflow[node]:
                for input in workflow[node]["inputs"].values():
                    if isinstance(input, str) and any(
                        input.endswith(ft) for ft in download_filetypes
                    ):
                        models_to_download.append(input)

        models_not_found = []
        for model in models_to_download:
            status, similar_models = self.model_downloader.download_model(model)
            if not status:
                models_not_found.append({
                    'model': model,
                    'similar_models': similar_models
                })
            else:
                models_downloaded = True

        for model in extra_models_list:
            status = self.model_downloader.download_file(model["filename"], model["url"], model["dest"])
            if status:
                models_downloaded = True
                for m in models_not_found:
                    if m['model'] == model['filename']:
                        models_not_found.remove(m)
                        break

        return {
            'data': {'models_not_found': models_not_found, 'models_downloaded': models_downloaded},
            'message': 'model(s) not found' if len(models_not_found) else '',
            'status': False if len(models_not_found) else True,
        }
    
    def download_custom_nodes(self, workflow, extra_node_urls) -> dict:
        nodes_installed = False

        # installing missing nodes
        missing_nodes = self.filter_missing_node(workflow)
        if len(missing_nodes):
            app_logger.log(LoggingType.INFO, f"Installing {len(missing_nodes)} custom nodes")
        for node in missing_nodes:
            app_logger.log(LoggingType.DEBUG, f"Installing {node['title']}")
            if node['installed'] in ['False', False]:
                nodes_installed = True
                status = self.comfy_api.install_custom_node(node)
                if status != {}:
                    app_logger.log(LoggingType.ERROR, "Failed to install custom node ", node["title"])

        # installing custom git repos
        if len(extra_node_urls):
            custom_node_list = self.comfy_api.get_all_custom_node_list()
            custom_node_list = custom_node_list["custom_nodes"]
            url_node_map = {}
            for node in custom_node_list:
                if node['reference'] not in url_node_map:
                    url_node_map[node['reference']] = [node]
                else:
                    url_node_map[node['reference']].append(node)

            for git_url in extra_node_urls:
                nodes_to_install = []
                if git_url in url_node_map:
                    for node in url_node_map[git_url]:
                        nodes_to_install.append(node)
                else:
                    node = {
                            'author': "",
                            'title': "",
                            'reference': git_url,
                            'files': [git_url],
                            'install_type': 'git-clone',
                            'description': "",
                            'installed': 'False'
                        }
                    nodes_to_install.append(node)
                
                for n in nodes_to_install:
                    nodes_installed = True
                    status = self.comfy_api.install_custom_node(n)
                    if status != {}:
                        app_logger.log(LoggingType.ERROR, "Failed to install custom node ", n["title"])

        return {
            'data': {'nodes_installed': nodes_installed},
            'message': '',
            'status': True
        }

    def load_workflow(self, workflow_path):
        if not os.path.exists(workflow_path):
            return None

        try:
            with open(workflow_path, 'r') as file:
                data = json.load(file)

            if not ComfyMethod.is_api_json(data):
                return None
        except Exception as e:
            app_logger.log(LoggingType.ERROR, "Exception: ", str(e))
            return None   

        return data

    def predict(self, workflow_path, file_path_list=[], extra_models_list=[], extra_node_urls=[], stop_sever_after_completion=False, output_ext=None):
        # TODO: add support for image and normal json files
        workflow = self.load_workflow(workflow_path)
        if not workflow:
            app_logger.log(LoggingType.ERROR, "Invalid workflow file")
            return

        # cloning comfy repo
        app_logger.log(LoggingType.DEBUG, "cloning comfy repo")
        comfy_repo_url = "https://github.com/comfyanonymous/ComfyUI"
        comfy_manager_url = "https://github.com/ltdrdata/ComfyUI-Manager"
        if not os.path.exists("ComfyUI"):
            Repo.clone_from(comfy_repo_url, "ComfyUI")
        if not os.path.exists("./ComfyUI/custom_nodes/ComfyUI-Manager"):
            os.chdir("./ComfyUI/custom_nodes/")
            Repo.clone_from(comfy_manager_url, "ComfyUI-Manager")
            os.chdir("../../")
        
        # installing requirements
        app_logger.log(LoggingType.DEBUG, "Checking comfy requirements")
        subprocess.run(["pip", "install", "-r", "./ComfyUI/requirements.txt"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        # start the comfy server if not already running
        self.start_server()

        # download custom nodes
        res_custom_nodes = self.download_custom_nodes(workflow, extra_node_urls)
        if not res_custom_nodes['status']:
            app_logger.log(LoggingType.ERROR, res_custom_nodes['message'])
            return

        # download models if not already present
        res_models = self.download_models(workflow, extra_models_list)
        if not res_models['status']:
            app_logger.log(LoggingType.ERROR, res_models['message'])
            if len(res_models['data']['models_not_found']):
                app_logger.log(LoggingType.INFO, "Please provide custom model urls for the models listed below or modify the workflow json to one of the alternative models listed")
                for model in res_models['data']:
                    print("Model: ", model['model'])
                    print("Alternatives: ")
                    if len(model['similar_models']):
                        for alternative in model['similar_models']:
                            print(" - ", alternative)
                    else:
                        print(" - None")
                    print("---------------------------")
            return
        
        # restart the server if custom nodes or models are installed
        if res_custom_nodes['nodes_installed'] or res_models['models_downloaded']:
            app_logger.log(LoggingType.INFO, "Restarting the server")
            self.stop_server()
            self.start_server()

        if len(file_path_list):
            for filepath in file_path_list:
                copy_files(filepath, "./ComfyUI/input/", overwrite=True)

        # get the result
        client_id = str(uuid.uuid4())
        ws = websocket.WebSocket()
        print(SERVER_ADDR + ":" + str(APP_PORT))
        ws.connect("ws://{}/ws?clientId={}".format("127.0.0.1:8188", client_id))
        node_output_list = self.get_output(ws, workflow_path, client_id, output_ext)

        # stopping the server
        output_list = copy_files("./ComfyUI/output", "./output", overwrite=False, delete_original=True)
        if stop_sever_after_completion:
            self.stop_server()

        # TODO: implement a proper way to remove the log
        log_file_list = glob.glob("comfyui*.log")
        for file in log_file_list:
            if os.path.exists(file):
                os.remove(file)
        
        return output_list