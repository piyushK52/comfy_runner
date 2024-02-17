from inf import ComfyRunner

runner = ComfyRunner()
output = runner.predict(
    workflow_input="examples/steerable_motion/workflow_api.json",
    file_path_list=[
        "./examples/vid2vid/boy_sunshine.png",
        "./examples/vid2vid/king_dark.png"
    ],
    stop_server_after_completion=True
)

print("final output: ", output)

# ***************** EXAMPLES ******************

# -- steerable motion
# runner.predict(
#     workflow_path="examples/steerable_motion/workflow_api.json",
#     file_path_list=[
#         "./examples/vid2vid/boy_sunshine.png",
#         "./examples/vid2vid/king_dark.png"
#     ],
#     stop_server_after_completion=True
# )

# -- vid2vid sample
# runner.predict(
#     workflow_input="examples/vid2vid/workflow_api.json",
#     file_path_list=[
#         "./examples/vid2vid/lab.mp4",
#         "./examples/vid2vid/boy_sunshine.png",
#         "./examples/vid2vid/king_dark.png"
#     ],
#     stop_server_after_completion=True
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
#     extra_node_urls=["https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite"],
#     stop_server_after_completion=True
# )