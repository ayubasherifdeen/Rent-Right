"""
config/asgi.py

ASGI entry point — ready for future WebSocket support
(e.g. real-time negotiation updates, maintenance notifications).

Currently unused — the app is WSGI. This file is here so switching
to async later requires no restructuring.
"""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')

application = get_asgi_application()

