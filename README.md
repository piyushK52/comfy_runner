
# Comfy Runner

Setup and run comfy workflows. This tool automatically downloads all the neccessary nodes and models and executes the provided workflow. This repo can make it easier for people to use ComfyUI as a backend.

Follow this demo video to quickly set it up or follow the "How to use" guide below

https://github.com/piyushK52/comfy_runner/assets/34690994/29fa06eb-410d-4a60-a129-ba4995fa1d4f





## Features

- Auto installs missing nodes
- Auto downloads workflow models. (Check the data folder for supported models)
- Executes the workflow without starting the UI server
- Suggests similar models if the ones in the workflow are not found
- Link to custom nodes and models can be provided for installation/Setup

## How to use

### 1. Save the workflow as API json
After loading the workflow into ComfyUI turn on the "Enable Dev mode Options" from the ComfyUI settings. Click on "Save (API format)" button to save the workflow in API json format.

### 2. Clone the repo
Clone the repo and install the requirements. Below is a setup using python virtual environment.
```sh
git clone https://github.com/piyushK52/comfy-runner
python3 -m venv venv
source ./venv/bin/activate
pip install -r requirements.txt
```

### 3. Run 
Provide the path to your workflow and input files. (Check main.py for sample code)
```sh
from comfy_runner.inf import ComfyRunner

runner = ComfyRunner()
output = runner.predict(
    workflow_input="comfy_runner/examples/txt2img/workflow_api.json",
    stop_server_after_completion=True,
)

print("final output: ", output)
```

Other parameters that can be passed in this method
| Param | Description |
| --- | --- |
| workflow_input | API json of the workflow. Can be a filepath or str |
| file_path_list | Files to copy inside the '/input' folder which are being used in the workflow |
| extra_models_list | Extra models to be downloaded |
| extra_node_urls | Extra nodes to be downloaded (with the option to specify commit version) |
| stop_server_after_completion | Stop server as soon as inference completes (or fails) |
| clear_comfy_logs | Clears the temp comfy logs after every inference |
| output_folder | For storing inference output (defaults to  ./output) |
| output_node_ids | Nodes to look in for the output |
| ignore_model_list | These models won't be downloaded (in cases where these are manually placed) |
| client_id | This can be used as a tag for the generations |
| comfy_commit_hash | Specific comfy commit to checkout |

If you are running multiple queries then you can use ```stop_server_after_completion=False``` and after completion manually stop the server using ```runner.stop_server()``` 
Please check the main.py for some code examples or the video above.

You can also stop the current generation using ```stop_current_generation```
```sh
runner = ComfyRunner()
runner.stop_current_generation(client_id=xyz, retry_window=10)    # xyz is the client_id used for starting the gen
```

## Roadmap

- [ ]  Add support for normal workflow json and image files
- [ ]  Publish this as a library for easy usage

## Feedback

Open issues/discussion if you want to suggest changes or have feature requests. This repo was basically created in an effort to make it easier for people to use ComfyUI as a backend in their apps and decrease their setup time.
