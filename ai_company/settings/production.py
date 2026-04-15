"""
PythonAnywhere production settings.
Python 3.12, PostgreSQL 12+ (port 14110).
"""
from .base import *

ALLOWED_HOSTS = [os.environ.get('PYTHONANYWHERE_DOMAIN', 'yourusername.pythonanywhere.com')]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'yourusername$ai_company'),
        'USER': os.environ.get('DB_USER', 'yourusername'),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', 'yourusername-postgres.pythonanywhere-services.com'),
        'PORT': os.environ.get('DB_PORT', '14110'),
    }
}

STATIC_ROOT = os.environ.get('STATIC_ROOT', '/home/yourusername/ai_company/staticfiles/')
MEDIA_ROOT = os.environ.get('MEDIA_ROOT', '/home/yourusername/ai_company/media/')

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
