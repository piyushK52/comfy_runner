import requests
from fuzzywuzzy import process
import os
import shutil

def get_file_size(url):
    response = requests.get(url, stream=True)
    try:
        total_size = int(response.headers.get('content-length', 0))
        return total_size
    except Exception as e:
        return None
    
def fuzzy_text_match(text_list, query, limit = 2):
    matches = process.extract(query, text_list, limit=limit)
    return [match for match, score in matches if score > 90]

def is_ignored_file(filename):
    ignore_list = ['.DS_Store', '.gitignore', '_output_images_will_be_put_here', '__MACOSX']
    return any(ignored_file.lower() in filename.lower() for ignored_file in ignore_list)


def copy_files(source_path, destination_path, overwrite=False, delete_original=False):
    os.makedirs(destination_path, exist_ok=True)
    destination_file = os.path.join(destination_path, os.path.basename(source_path))

    if os.path.isdir(source_path):
        res = []
        for file in os.listdir(source_path):
            if not os.path.isdir(os.path.join(source_path, file)) and not is_ignored_file(file):
                res.append(copy_files(os.path.join(source_path, file), destination_path, overwrite, delete_original))
        return res
    else:
        if not overwrite and os.path.exists(destination_file):
            base_name, extension = os.path.splitext(os.path.basename(source_path))
            count = 1
            while os.path.exists(os.path.join(destination_path, f"{base_name}_{count}{extension}")):
                count += 1
            unique_name = f"{base_name}_{count}{extension}"
            destination_file = os.path.join(destination_path, unique_name)
        else:
            unique_name = os.path.basename(source_path)

        shutil.copy2(source_path, destination_file)
        if delete_original:
            os.remove(source_path)

        return unique_name