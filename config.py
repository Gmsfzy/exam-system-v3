import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY')
    DASHSCOPE_API_KEY = os.getenv('DASHSCOPE_API_KEY')
    DB_NAME = 'exam_system.db'