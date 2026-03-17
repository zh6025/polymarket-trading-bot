import logging
import requests
import zlib
import gzip

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class HTTPClient:
    def __init__(self, base_url):
        self.base_url = base_url

    def get(self, endpoint, **kwargs):
        url = f"{self.base_url}{endpoint}"
        logger.info(f'GET request to {url}')
        response = requests.get(url, **kwargs)
        response.raise_for_status()
        return response.json()

    def post(self, endpoint, data, **kwargs):
        url = f"{self.base_url}{endpoint}"
        logger.info(f'POST request to {url}')
        response = requests.post(url, json=data, **kwargs)
        response.raise_for_status()
        return response.json()

# Decompression functions

def decompress_gzip(data):
    return gzip.decompress(data)


def decompress_zlib(data):
    return zlib.decompress(data)

# Helper functions

def log_response(response):
    logger.info('Response: %s', response)


# Example usage
# if __name__ == '__main__':
#     client = HTTPClient('https://api.example.com')
#     response = client.get('/data')
#     log_response(response)