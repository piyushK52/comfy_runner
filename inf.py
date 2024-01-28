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
from constants import APP_PORT, MODEL_DOWNLOAD_PATH_LIST, SERVER_ADDR
from utils.comfy.api import ComfyAPI
from utils.comfy.methods import ComfyMethod
from utils.file_downloader import ModelDownloader

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
            self.server_process = subprocess.Popen(command, shell=True)

            # waiting for server to start accepting requests
            while not self.is_server_running():
                time.sleep(0.5)
            
            print("comfy server is running")
        else:
            try:
                if not self.comfy_api.health_check():
                    raise Exception(f"Port {APP_PORT} blocked")
                else:
                    print("Server already running")
            except Exception as e:
                raise Exception(f"Port {APP_PORT} blocked")

    def find_process_by_port(self, port):
        pid = None
        for proc in psutil.process_iter(attrs=['pid', 'name', 'connections']):
            try:
                if proc and 'connections' in proc.info and proc.info['connections']:
                    for conn in proc.info['connections']:
                        if conn.status == psutil.CONN_LISTEN and conn.laddr.port == port:
                            print(f"Process {proc.info['pid']} (Port {port})")
                            pid = proc.info['pid']
                            break
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        
        return pid

    def stop_server(self):
        pid = self.find_process_by_port(APP_PORT)
        if pid:
            psutil.Process(pid).terminate()

    def queue_prompt(self, prompt, client_id):
        p = {"prompt": prompt, "client_id": client_id}
        data = json.dumps(p).encode('utf-8')
        req =  urllib.request.Request(self.SERVER_URL + self.QUEUE_PROMPT_URL, data=data)
        return json.loads(urllib.request.urlopen(req).read())

    def get_output(self, ws, prompt, client_id, ext=None):
        prompt_id = self.queue_prompt(prompt, client_id)['prompt_id']
        
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

        # fetching results
        history = self.get_history(prompt_id)[prompt_id]
        output_list = []
        for o in history['outputs']:
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

        for model in models_to_download:
            self.model_downloader.download_model(model)

        for model in extra_models_list:
            self.model_downloader.download_file(model["filename"], model["url"], model["dest"])

        return {
            'data': None,
            'message': '',
            'status': True
        }
    
    def download_custom_nodes(self, workflow, extra_node_urls) -> dict:
        # installing missing nodes
        missing_nodes = self.filter_missing_node(workflow)
        for node in missing_nodes:
            if node['installed'] in ['False', False]:
                status = self.comfy_api.install_custom_node(node)
                if status != {}:
                    print("Error: Failed to install custom node ", node["title"])

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
                    status = self.comfy_api.install_custom_node(n)
                    if status != {}:
                        print("Error: Failed to install custom node ", n["title"])

        return {
            'data': None,
            'message': '',
            'status': True
        }

    def copy_files(self, file_path_dict, overwrite=False):
        pass

    def load_workflow(self, workflow_path):
        if not os.path.exists(workflow_path):
            return None

        try:
            with open(workflow_path, 'r') as file:
                data = json.load(file)

            if not ComfyMethod.is_api_json(data):
                return None
        except Exception as e:
            print("Exception: ", str(e))
            return None   

        return data

    def predict(self, workflow_path, file_path_dict={}, extra_models_list=[], extra_node_urls=[], stop_sever_after_completion=False, output_ext=None):
        # TODO: add support for image and normal json files
        workflow = self.load_workflow(workflow_path)
        if not workflow:
            print("Error: Invalid workflow file")
            return

        # cloning comfy repo
        print("cloning comfy repo")
        comfy_repo_url = "https://github.com/comfyanonymous/ComfyUI"
        comfy_manager_url = "https://github.com/ltdrdata/ComfyUI-Manager"
        if not os.path.exists("ComfyUI"):
            Repo.clone_from(comfy_repo_url, "ComfyUI")
        if not os.path.exists("./ComfyUI/custom_nodes/ComfyUI-Manager"):
            os.chdir("./ComfyUI/custom_nodes/")
            Repo.clone_from(comfy_manager_url, "ComfyUI-Manager")
            os.chdir("../../")
        
        # installing requirements
        subprocess.run(["pip", "install", "-r", "./ComfyUI/requirements.txt"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        # start the comfy server if not already running
        self.start_server()

        # download custom nodes
        res = self.download_custom_nodes(workflow, extra_node_urls)
        if not res['status']:
            raise Exception(res['message'])     # when node links are not available

        # download models if not already present
        res = self.download_models(workflow, extra_models_list)
        if not res['status']:
            raise Exception(res['message'])     # when model links are not available

        # if len(file_path_dict.keys()):
        #     for filename, filepath in file_path_dict.items():
        #         self.copy_files(filepath, "./ComfyUI/input/", overwrite=True)

        # # get the result
        # client_id = str(uuid.uuid4())
        # ws = websocket.WebSocket()
        # ws.connect("ws://{}/ws?clientId={}".format(self.server_address, client_id))
        # output_list = self.get_output(ws, workflow_path, client_id, output_ext)

        # print("output: ", output_list)

        # # stopping the server
        # self.copy_files("./ComfyUI/output", "./")
        # if stop_sever_after_completion:
        #     self.stop_server()
        
        # return output_list
        return []