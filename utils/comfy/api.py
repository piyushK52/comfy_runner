import json
import requests


class BaseAPI:
    def __init__(self, base_url):
        self.base_url = base_url

    def _get_headers(self, content_type="application/json"):
        headers = {}
        # headers["Authorization"] = f"Bearer {auth_token}"
        if content_type:
            headers["Content-Type"] = content_type

        return headers

    def http_get(self, url, params=None):
        res = requests.get(
            self.base_url + url, params=params, headers=self._get_headers()
        )
        return res.json()

    def http_post(self, url, data={}, file_content=None, json_output=True):
        if file_content:
            files = {"file": file_content}
            res = requests.post(
                self.base_url + url,
                data=data,
                files=files,
                headers=self._get_headers(None),
            )
        else:
            res = requests.post(
                self.base_url + url, json=data, headers=self._get_headers()
            )

        return res.json() if json_output else res

    def http_put(self, url, data=None):
        res = requests.put(self.base_url + url, json=data, headers=self._get_headers())
        return res.json()

    def http_delete(self, url, params=None):
        res = requests.delete(
            self.base_url + url, params=params, headers=self._get_headers()
        )
        return res.json()


class ComfyAPI(BaseAPI):
    def __init__(self, server_addr, port):
        super().__init__(base_url=f"{server_addr}:{port}")
        self.server_addr = server_addr
        self.port = port

        self._set_urls()

    def _set_urls(self):
        self.SERVER_URL = f"{self.server_addr}:{self.port}"

        self.QUEUE_PROMPT_URL = "/prompt"
        self.HISTORY_URL = "/history"
        self.CUSTOM_NODE_LIST_URL = "/customnode/getlist"
        self.CUSTOM_NODE_URL = (
            "/customnode/"  # mode can be added infront {install, uninstall, update}
        )
        self.REGISTERED_NODE_LIST_URL = "/object_info"
        self.NODE_MAPPING_LIST_URL = "/customnode/getmappings"
        self.MODEL_LIST_URL = "/externalmodel/getlist"
        self.CUSTOM_MODEL_URL = "/model/"
        self.INTERRUPT_URL = "/interrupt"
        self.QUEUE_URL = "/queue"

    def get_all_custom_node_list(self):
        return self.http_get(self.CUSTOM_NODE_LIST_URL + "?mode=local")

    def get_all_model_list(self):
        res = self.http_get(self.MODEL_LIST_URL + "?mode=local")
        return res["models"] if "models" in res else []

    # TODO: add health check api
    def health_check(self):
        res = requests.get(self.SERVER_URL + self.HISTORY_URL + "/123")
        return True if res.status_code == 200 else False

    def get_history(self, prompt_id):
        return self.http_get(self.HISTORY_URL + "/" + str(prompt_id))

    def install_custom_node(self, node):
        return self.http_post(self.CUSTOM_NODE_URL + "install", data=node)

    def install_custom_model(self, model):
        return self.http_post(self.CUSTOM_MODEL_URL + "install", data=model)

    def get_node_mapping_list(self):
        return self.http_get(self.NODE_MAPPING_LIST_URL + "?mode=local")

    def get_registered_nodes(self):
        return self.http_get(self.REGISTERED_NODE_LIST_URL)

    def queue_prompt(self, prompt, client_id):
        p = {"prompt": prompt, "client_id": client_id}
        return self.http_post(self.QUEUE_PROMPT_URL, data=p)

    # NOTE: stops the current generation in progress
    def interrupt_prompt(self):
        return self.http_post(self.INTERRUPT_URL, data={}, json_output=False)

    def get_queue(self):
        return self.http_get(self.QUEUE_URL)
