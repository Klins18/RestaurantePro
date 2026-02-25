import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = 'sqlite:///restaurante_pro.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    FLASK_HOST = os.environ.get('FLASK_HOST', '0.0.0.0')
    FLASK_PORT = int(os.environ.get('FLASK_PORT', 5000))
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'Admin123!')
    RESTAURANTE_NOMBRE = os.environ.get('RESTAURANTE_NOMBRE', 'Rest. Tco. Marangani')
    UPLOAD_FOLDER = 'static/uploads'
    TIMEZONE = 'America/Lima'
