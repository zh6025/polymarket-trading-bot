import logging
import requests
import zlib
import gzip
import time

# Set up logging
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class APIClient:
    """HTTP API Client for making requests"""
    def __init__(self, base_url='https://polymarket.com'):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})

    def get(self, url, **kwargs):
        logger.info(f'GET {url}')
        response = self.session.get(url, **kwargs, timeout=10)
        response.raise_for_status()
        return response.json()

    def post(self, url, data=None, **kwargs):
        logger.info(f'POST {url}')
        response = self.session.post(url, json=data, **kwargs, timeout=10)
        response.raise_for_status()
        return response.json()

# Logging functions
def log_info(msg):
    logger.info(msg)

def log_error(msg):
    logger.error(msg)

def log_warn(msg):
    logger.warning(msg)

def sleep(ms):
    """Sleep for milliseconds"""
    time.sleep(ms / 1000)

def round_to_tick(price, tick_size):
    """Round price to nearest tick size"""
    if tick_size <= 0:
        return price
    decimals = len(str(tick_size).split('.')[-1]) if '.' in str(tick_size) else 0
    return round(round(price / tick_size) * tick_size, decimals)
