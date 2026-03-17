import os
import re

class Config:
    def __init__(self):
        self.api_key = self.get_env_variable('API_KEY')
        self.api_secret = self.get_env_variable('API_SECRET')
        self.database_url = self.get_env_variable('DATABASE_URL')

    def get_env_variable(self, var_name):
        value = os.getenv(var_name)
        if not value:
            raise ValueError(f'Environment variable {var_name} is required.')
        return value

    def validate(self):
        if not re.match(r'^[A-Za-z0-9]+$', self.api_key):
            raise ValueError('API_KEY is not valid. It must be alphanumeric.')
        # Add more validation as needed

# Example usage:
# config = Config()
# config.validate()