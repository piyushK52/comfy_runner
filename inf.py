import json
import os
import time
import psutil
import subprocess
import urllib.request
import websocket
import uuid
from utils.file import is_api_json

from utils.image import get_png_metadata, get_webp_metadata

APP_PORT = 8188
SERVER_ADDR = "http://127.0.0.1:8188"

class ComfyRunner:
    def __init__(self):
        self._set_urls()

    def _set_urls(self):
        self.SERVER_URL = SERVER_ADDR

        self.QUEUE_PROMPT_URL = "/prompt"
        self.HISTORY_URL = "/history"
        self.CUSTOM_NODE_LIST = "/customnode/getlist"

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
                # improper sol, will fix later
                with urllib.request.urlopen(self.SERVER_URL + self.HISTORY_URL + "/123") as response:
                    if response.status != 200:
                        raise Exception(f"Port {APP_PORT} blocked")
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

    def clone_repository(self, repo_url):
        try:
            if not os.path.exists("./ComfyUI"):
                subprocess.run(["git", "clone", repo_url], check=True)
            subprocess.run(["pip", "install", "-r", "./ComfyUI/requirements.txt"], check=True)
            print(f"Successfully cloned git repo")
        except subprocess.CalledProcessError as e:
            print(f"Error cloning repository: {e}")

    def get_history(self, prompt_id):
        with urllib.request.urlopen(self.SERVER_URL + self.HISTORY_URL + "/" + str(prompt_id)) as response:
            return json.loads(response.read())

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

    def download_models(self, workflow, extra_models_dict) -> dict:
        return {
            'data': None,
            'message': '',
            'status': True
        }
    
    def download_custom_nodes(self, workflow, extra_node_dict) -> dict:
        req =  urllib.request.Request(self.SERVER_URL + self.QUEUE_PROMPT_URL)
        data = json.loads(urllib.request.urlopen(req).read())
        print("data found: ", data)
        return {
            'data': None,
            'message': '',
            'status': True
        }

    def copy_files(self, file_path_dict, overwrite=False):
        pass

    def load_graph_data(self, workflow_data):
        pass

    def load_api_data(self, workflow_data):
        pass

    def load_template_data(self, workflow_data):
        pass
    
    def load_workflow(self, workflow_path):
        workflow_loaded = True

        try:
            _, file_extension = os.path.splitext(workflow_path)
            # handling image files
            if file_extension.lower() in ['.png', '.webp']:
                pngInfo = get_png_metadata(workflow_path) if file_extension.lower() == ".png" else get_webp_metadata(workflow_path)
                if pngInfo:
                    if pngInfo.workflow or pngInfo.Workflow:
                        data = pngInfo.workflow or pngInfo.Workflow
                        self.load_graph_data(json.loads(data))
                    elif pngInfo.prompt:
                        self.load_api_data(json.loads(pngInfo.prompt))
                    else:
                        workflow_loaded = False
                else:
                    workflow_loaded = False
            
            # handling json files
            elif file_extension.lower() == '.json':
                with open(workflow_path, 'r') as file_reader:
                    json_content = json.load(file_reader)
                    if json_content.get('templates'):
                        self.load_template_data(json_content)
                    elif is_api_json(json_content):
                        self.load_api_data(json_content)
                    else:
                        self.load_graph_data(json_content)
        except Exception as e:
            print("Exception: ", e)
            workflow_loaded = False
        
        return workflow_loaded


    def predict(self, workflow_path, file_path_dict={}, extra_models_dict={}, extra_node_dict={}, stop_sever_after_completion=False, output_ext=None):
        # validate workflow. converts all kinds of workflow (image, json, api json) into api json before loading
        status = self.load_workflow(workflow_path)
        if not status:
            print("Error: Invalid workflow file")
            return

        # cloning comfy repo
        comfy_repo_url = "https://github.com/comfyanonymous/ComfyUI"
        self.clone_repository(comfy_repo_url)

        # start the comfy server if not already running
        self.start_server()

        # download custom nodes
        res = self.download_custom_nodes(workflow_path, extra_node_dict)
        if not res['status']:
            raise Exception(res['message'])     # when node links are not available

        # download models if not already present
        # res = self.download_models(workflow_path, extra_models_dict)
        # if not res['status']:
        #     raise Exception(res['message'])     # when model links are not available

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