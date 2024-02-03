import ast
import json
import os
import shutil
from typing import List
import uuid
import zipfile
from cog import BasePredictor, Input, Path
from inf import ComfyRunner


class Predictor(BasePredictor):
    def setup(self):
        self.comfy_runner = ComfyRunner()

    def _copy_files_in_AD_repo(self, *args, **kwargs):
        current_directory = os.getcwd()
        print("Current Working Directory:", current_directory)
        files = os.listdir(current_directory)

        # Print the list of files
        for file in files:
            print(file)
        destination_folder = "./" if 'loc' not in kwargs else kwargs['loc']
        if not os.path.exists(destination_folder):
            os.makedirs(destination_folder)
            
        res = []

        for filepath in args:
            print("filepath in array: ", filepath)
            filename = os.path.basename(filepath)
            destination_path = os.path.join(destination_folder, filename)
            shutil.copy(filepath, destination_path)
            print("----- dest path: ", destination_path)
            path = (destination_path[15:] if "ComfyUI/tmp/input" in destination_path else filename)
            print("---- appending: ", path)
            res.append(path)
            print("copying file: ", filename, destination_folder)
        
        return res

    def predict(
        self,
        workflow_json: Path = Input(description="workflow API json"), 
        file_list: Path = Input(description="File list (.zip file)"),
        extra_models_list: str = Input(description="extra models to download", default="[]"), 
        extra_node_urls: str = Input(description="extra nodes to download", default="[]"),
    ) -> List[Path]:
        """Run a single prediction on the model"""
        stop_server_after_completion = True
        clear_comfy_logs = True
        
        # filename = str(uuid.uuid4())
        # with open(filename, 'w') as json_file:
        #     json.dump(workflow_json, json_file, indent=4)

        extracted_dir = os.path.dirname(file_list)
        extracted_file_paths = []
        with zipfile.ZipFile(file_list, 'r') as zip_ref:
            for file_info in zip_ref.infolist():
                if not file_info.is_dir():
                    if not file_info.filename.startswith('__MACOSX') and not file_info.filename.startswith('.DS_Store'):
                        zip_ref.extract(file_info, extracted_dir)
                        extracted_file_paths.append(os.path.join(extracted_dir, file_info.filename))
        
        # copy img inside comfy
        filename_list = self._copy_files_in_AD_repo(*extracted_file_paths)
        extra_models_list = ast.literal_eval(extra_models_list)
        extra_node_urls = ast.literal_eval(extra_node_urls)

        output_list = self.comfy_runner.predict(
            workflow_path=workflow_json,
            file_path_list=filename_list,
            extra_models_list=extra_models_list,
            extra_node_urls=extra_node_urls,
            stop_server_after_completion=stop_server_after_completion,
            clear_comfy_logs=clear_comfy_logs
        )

        return [Path(file) for file in output_list]
