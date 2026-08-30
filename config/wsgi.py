"""
config/wsgi.py

WSGI entry point for production (Gunicorn, uWSGI).
Railway.app and DigitalOcean App Platform both use this.

Start command:
    gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')  # Change to 'config.settings.production' for production

application = get_wsgi_application()

