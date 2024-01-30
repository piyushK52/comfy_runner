
# Comfy Runner

Setup and run comfy workflows. This tool automatically downloads all the neccessary nodes and models and executes the provided workflow. This repo can make it easier for people to use ComfyUI as a backend.


https://github.com/piyushK52/comfy-runner/assets/34690994/a6e25547-f721-4623-b31e-e9165c67548a


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
cd comfy-runner
python3 -m venv venv
source ./venv/bin/activate
pip install -r requirements.txt
```

### 3. Run 
Provide the path to your workflow and input files. (Check main.py for sample code)
```sh
from inf import ComfyRunner

runner = ComfyRunner()
runner.predict(
    workflow_path="examples/img2img/i2i_workflow_api.json",
    stop_sever_after_completion=True
)
```

If you are running multiple queries then you can use ```stop_sever_after_completion=False``` and after completion manually stop the server using ```runner.stop_server()``` 

## Roadmap

- [ ]  Add support for normal workflow json and image files
- [ ]  Add support for fetching models through Civit API
- [ ]  Add function to generate static python code for the workflow
- [ ]  Publish this as a library for easy usage

## Feedback

Open issues/discussion if you want to suggest changes or have feature requests. This repo was basically created in an effort to make it easier for people to use ComfyUI as a backend in their apps and decrease their setup time.
