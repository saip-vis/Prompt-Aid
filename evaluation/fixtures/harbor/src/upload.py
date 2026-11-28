# Image upload validates file type and rejects oversized photos before storage.
def validate_upload(filename, size):
    return filename.endswith('.png') and size < 1000000
