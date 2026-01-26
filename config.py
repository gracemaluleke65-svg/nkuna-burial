import os
from datetime import timedelta

class Config:
    """Base configuration"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///nkuna.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = 'static/uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    
    # Application settings
    APP_NAME = "Nkuna Burial Society"
    APP_SLOGAN = "Protecting Your Legacy, Honoring Your Loved Ones"
    
    # Fee settings
    SERVICE_FEE_PERCENT = 2.5
    SERVICE_FEE_MIN = 10.0
    CLAIM_FEE_PERCENT = 1.0
    CLAIM_FEE_MIN = 50.0
    LATE_FEE = 50.0
    REGISTRATION_FEE = 100.0
    
    # Transaction limits
    MAX_DEPOSIT_PER_TRANSACTION = 50000.0
    MAX_BALANCE = 100000.0
    
    # Age bands for premium calculation
    AGE_BANDS = {
        '0-18': 50.0,
        '19-30': 100.0,
        '31-45': 150.0,
        '46-60': 200.0,
        '61-75': 250.0,
        '76+': 300.0
    }
    
    # Flask-Login settings
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    SESSION_PROTECTION = 'strong'
    
    @staticmethod
    def init_app(app):
        pass


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    SQLALCHEMY_ECHO = False


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    # Handle Render's PostgreSQL URL format
    db_url = os.environ.get('DATABASE_URL', '')
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_DATABASE_URI = db_url or None
    
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'pool_recycle': 3600,
        'pool_pre_ping': True
    }

class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}