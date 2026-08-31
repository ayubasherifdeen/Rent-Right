"""
WSGI entry point for production (Gunicorn, uWSGI).
Start command:
    gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')  # Change to 'config.settings.production' for production

application = get_wsgi_application()

