import requests

def get_file_size(url):
    response = requests.get(url, stream=True)
    try:
        total_size = int(response.headers.get('content-length', 0))
        return total_size
    except Exception as e:
        return None