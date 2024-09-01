#########################################################################################################
# NOTE: This file is supposed to be run outside comfy_runner. Please check the video in the README.md. ##
#########################################################################################################
from .inf import ComfyRunner

runner = ComfyRunner()
output = runner.predict(
    workflow_input="examples/txt2img/workflow_api.json",
    file_path_list=[
        "./examples/vid2vid/boy_sunshine.png",
        "./examples/vid2vid/king_dark.png",
    ],
    stop_server_after_completion=True,
)

print("final output: ", output)

# ***************** EXAMPLES ******************

# -- vid2vid sample
# runner.predict(
#     workflow_input="examples/vid2vid/workflow_api.json",
#     file_path_list=[
#         "./examples/vid2vid/lab.mp4",
#         "./examples/vid2vid/boy_sunshine.png",
#         "./examples/vid2vid/king_dark.png"
#     ],
#     stop_server_after_completion=True,
#     ignore_model_list=[{
#     "filename": "sd_xl_base_18897557.0.safetensors",
#     "filepath": "./ComfyUI/models/checkpoints/sd_xl_base_18897557.0.safetensors"
# }]
# )

# -- sample params
# runner.predict(
#     workflow_input="examples/img2img/i2i_workflow_api.json",
#     extra_models_list=[
#         {
#             "filename": "mod_sdxl.safetensors",
#             "url": "https://civitai.com/api/download/models/299716",
#             "dest": "./ComfyUI/models/checkpoints/"
#         }
#     ],
#     extra_node_urls=[
#     {
#         "title": "ComfyUI-AnimateDiff-Evolved",
#         "url": "https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved",
#         "commit_hash": "bbb1280213d351abea9e87fd1f08ba5d47158ad5",
#     },
#     {
#         "title": "ComfyUI-Advanced-ControlNet",
#         "url": "https://github.com/Kosinkadink/ComfyUI-Advanced-ControlNet",
#         "commit_hash": "576426a73495609f7a565db8dd25d77c670574a3",
#     },
#     {
#         "title": "ComfyUI_FizzNodes",
#         "url": "https://github.com/FizzleDorf/ComfyUI_FizzNodes",
#         "commit_hash": "51a29ce041f504583efdd3b9488ee6144dfda7de",
#     },
# ],
#     stop_server_after_completion=True
# )
