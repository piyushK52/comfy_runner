import requests
from fuzzywuzzy import process
import os
import shutil
import psutil

from .logger import app_logger

from .logger import LoggingType

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
            if not is_ignored_file(file):   # not os.path.isdir(os.path.join(source_path, file)) and 
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

def find_process_by_port(port):
        pid = None
        for proc in psutil.process_iter(attrs=['pid', 'name', 'connections']):
            try:
                if proc and 'connections' in proc.info and proc.info['connections']:
                    for conn in proc.info['connections']:
                        if conn.status == psutil.CONN_LISTEN and conn.laddr.port == port:
                            app_logger.log(LoggingType.DEBUG, f"Process {proc.info['pid']} (Port {port})")
                            pid = proc.info['pid']
                            break
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        
        return pid

def find_file_in_directory(directory, target_file):
    for root, dirs, files in os.walk(directory):
        if target_file in files:
            return os.path.join(root, target_file)

    return None

def clear_directory(directory):
    for item in os.listdir(directory):
        item_path = os.path.join(directory, item)
        if os.path.isfile(item_path):
            os.remove(item_path)
        elif os.path.isdir(item_path):
            shutil.rmtree(item_path)

# recursively moves up directories till it finds the .git file (root of the repo)
def find_git_root(path):
    if '.git' in os.listdir(path):
        return path
    
    parent_path = os.path.abspath(os.path.join(path, os.pardir))
    return find_git_root(parent_path)