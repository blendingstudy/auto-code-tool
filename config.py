import os

class Config:
    OPENAI_APIKEY = os.environ.get('OpenaiAPI')
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'a_hard_to_guess_string'
