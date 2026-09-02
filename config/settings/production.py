"""
Usage: export DJANGO_SETTINGS_MODULE=config.settings.production
"""
from faulthandler import disable

from .base import *  # noqa
from decouple import Csv, config


#Core

DEBUG = True 
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='rentrigh-gh-staging.up.railway.app', cast=Csv())


#Database — PostgreSQL 
# Railway.app injects DATABASE_URL automatically.

import dj_database_url

DATABASES = {
    'default': dj_database_url.config(
        default=config('DATABASE_URL'),
        conn_max_age=600,
        ssl_require=True,
    ),
    'options': {
        'sslmode': 'disable',
      }  # Disable SSL verification for self-signed certificates
}


# ─── Security headers ─────────────────────────────────────────────────────────

SECURE_SSL_REDIRECT             = True
SECURE_HSTS_SECONDS             = 31536000      # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS  = True
SECURE_HSTS_PRELOAD             = True
SECURE_BROWSER_XSS_FILTER       = True
SECURE_CONTENT_TYPE_NOSNIFF     = True
X_FRAME_OPTIONS                 = 'DENY'
SESSION_COOKIE_SECURE           = True
CSRF_COOKIE_SECURE              = True
CSRF_TRUSTED_ORIGINS = ['https://rentrigh-gh-staging.up.railway.app']

# ─── Static files — WhiteNoise (already in base MIDDLEWARE) ───────────────────
# collectstatic → staticfiles/ → served by WhiteNoise with compression + caching

STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'


# ─── Media — Cloudinary ───────────────────────────────────────────────────────
# Cloudinary stores property photos and profile pictures.
# CLOUDINARY_URL is set in base.py from .env

import cloudinary          
import cloudinary.uploader
import cloudinary.api

DEFAULT_FILE_STORAGE    = 'cloudinary_storage.storage.MediaCloudinaryStorage'
INSTALLED_APPS_EXTRA    = ['cloudinary_storage', 'cloudinary']

# Append without mutating the base list
INSTALLED_APPS = INSTALLED_APPS + INSTALLED_APPS_EXTRA


# ─── Email — SendGrid / SMTP ──────────────────────────────────────────────────

EMAIL_BACKEND   = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST      = config('EMAIL_HOST',      default='smtp.sendgrid.net')
EMAIL_PORT      = config('EMAIL_PORT',      default=587,  cast=int)
EMAIL_USE_TLS   = True
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='apikey')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL  = config('DEFAULT_FROM_EMAIL', default='noreply@rentright.gh')


# ─── Logging — structured, to stdout for Railway/DO log aggregation ───────────

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json_like': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            'datefmt': '%Y-%m-%dT%H:%M:%S',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json_like',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'apps': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}


ARKESEL_DRY_RUN = False

