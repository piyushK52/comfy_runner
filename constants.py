APP_PORT = 8188
SERVER_ADDR = "http://127.0.0.1"

MODEL_DOWNLOAD_PATH_LIST = ["./data/civit_model_weights.json", "./data/replicate_model_weights.json", "./data/huggingface_weights.json"]
COMFY_MODEL_PATH_LIST = ["./ComfyUI/custom_nodes/ComfyUI-Manager/model-list.json", "./data/extra_comfy_weights.json"]

# enable this to view comfy console logs and other debug statements
DEBUG_LOG_ENABLED = True

# these models are downloaded automatically during the runtime (install manually if not present)
OPTIONAL_MODELS = ['stmfnet.pth']

MODEL_FILETYPES = [
    ".ckpt",
    ".safetensors",
    ".pt",
    ".pth",
    ".bin",
    ".onnx",
    ".torchscript",
    ".patch",
    ".gguf",
    ".ggml"
]