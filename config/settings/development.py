"""
config/settings/development.py

Local development environment. Never use in production.

Usage:
    export DJANGO_SETTINGS_MODULE=config.settings.development
    python manage.py runserver
"""
from django.core.checks import database

from .base import * 
import dj_database_url  # noqa — install: pip install dj-database-url psycopg2-binary

# ─── Core ─────────────────────────────────────────────────────────────────────

DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0',"endurance-rhyme-flaxseed.ngrok-free.dev", "*", "https://rentrigh-gh-staging.up.railway.app/"]


# ─── Database — SQLite for local speed ───────────────────────────────────────
# Switch to Postgres locally with:
#   brew install postgresql && createdb rentright_dev
#   then comment out SQLite block and uncomment Postgres block below.

DATABASES = {
    'default': dj_database_url.config(
        default=config('DATABASE_URL'),
        conn_max_age=600,
    )
}

# Postgres local (optional — uncomment when ready)
# DATABASES = {
#     'default': {
#         'ENGINE':   'django.db.backends.postgresql',
#         'NAME':     config('DB_NAME',     default='rentright_dev'),
#         'USER':     config('DB_USER',     default='postgres'),
#         'PASSWORD': config('DB_PASSWORD', default=''),
#         'HOST':     config('DB_HOST',     default='localhost'),
#         'PORT':     config('DB_PORT',     default='5432'),
#     }
# }


# ─── Email — print to console, no SMTP needed ─────────────────────────────────

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'


#

INSTALLED_APPS += ['debug_toolbar']
MIDDLEWARE.insert(0, 'debug_toolbar.middleware.DebugToolbarMiddleware')
INTERNAL_IPS = ['127.0.0.1']


# ─── Static files — served directly by Django runserver ───────────────────────

STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'


# ─── Media — local disk ───────────────────────────────────────────────────────

DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'


# ─── SMS — skip real API calls in dev, log to console instead ─────────────────

ARKESEL_DRY_RUN = False   # checked in apps/notifications/arkesel.py


# ─── Logging — show SQL queries and app logs in terminal ──────────────────────

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {
            'format': '[{levelname}] {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'django.db.backends': {
            'handlers': ['console'],
            'level': 'WARNING',    # set to DEBUG to see every SQL query
            'propagate': False,
        },
        'apps': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}

