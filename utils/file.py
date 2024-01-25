def is_api_json(data):
    return all('class_type' in v for v in data.values())