"""
config/settings/base.py

Shared settings inherited by all environments.
Never import this file directly in manage.py or wsgi.py —
always use development.py or production.py.
"""
from pathlib import Path
from decouple import config, Csv

import cloudinary
import cloudinary.uploader
from cloudinary.utils import cloudinary_url
import tailwind


  
# ─── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent.parent


# ─── Security ─────────────────────────────────────────────────────────────────

SECRET_KEY = config('SECRET_KEY', default='django-insecure-!@#4$%&*()_+secret-key-for-dev-only')
AUTH_USER_MODEL = 'accounts.User'


# ─── Application definition ───────────────────────────────────────────────────
TAILWIND_APP_NAME = "theme" 
DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
]

THIRD_PARTY_APPS = [
   'tailwind',
    'theme', # Populated in environment-specific settings as needed
]

LOCAL_APPS = [
    'apps.accounts.apps.AccountsConfig',
    'apps.listings',
    'apps.applications',
    'apps.tenancies',
    'apps.documents',
    'apps.negotiations',
    'apps.payments',
    'apps.maintenance',
    'apps.analytics',
    'apps.notifications',
    #  apps.notifications, etc. added as we build them
]


INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS



# ─── Middleware ───────────────────────────────────────────────────────────────

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',        # serve static in prod
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]


# ─── URLs & WSGI ──────────────────────────────────────────────────────────────

ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'


# ─── Templates ────────────────────────────────────────────────────────────────

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'theme' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.accounts.context_processors.sidebar_nav',
            ],
        },
    },
]


# ─── Password validation ──────────────────────────────────────────────────────

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ─── Internationalisation ─────────────────────────────────────────────────────

LANGUAGE_CODE = 'en-gb'
TIME_ZONE     = 'Africa/Accra'
USE_I18N      = True
USE_TZ        = True


# ─── Static & Media ───────────────────────────────────────────────────────────

STATIC_URL  = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'          # collectstatic output
STATICFILES_DIRS = [BASE_DIR / 'apps' / 'listings' / 'static']  # dev static files
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL  = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# ─── Auth redirects ───────────────────────────────────────────────────────────

LOGIN_URL           = '/accounts/login/'
LOGIN_REDIRECT_URL  = '/accounts/dashboard/'
LOGOUT_REDIRECT_URL = '/accounts/login/'


# ─── Sessions ─────────────────────────────────────────────────────────────────

SESSION_COOKIE_AGE     = 60 * 60 * 24 * 14    # 2 weeks
SESSION_COOKIE_HTTPONLY = True


# ─── Default primary key ──────────────────────────────────────────────────────

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ─── Third-party API keys (loaded from .env in all environments) ──────────────

PAYSTACK_SECRET_KEY  = config('PAYSTACK_SECRET_KEY',  default='')
PAYSTACK_PUBLIC_KEY  = config('PAYSTACK_PUBLIC_KEY',  default='')
ARKESEL_API_KEY      = config('ARKESEL_API_KEY',       default='')
ARKESEL_SENDER_NAME  = config('ARKESEL_SENDER_NAME',   default='RentRight')
ARKESEL_SENDER_ID  = config('ARKESEL_SENDER_ID',   default='RentRight')
CLOUDINARY_URL       = config('CLOUDINARY_URL',        default='')
ANTHROPIC_API_KEY = config("ANTHROPIC_API_KEY", default=None)

cloudinary.config(
    cloud_name = config('CLOUDINARY_CLOUD_NAME'),
    api_key =    config('CLOUDINARY_API_KEY'),
    api_secret = config('CLOUDINARY_API_SECRET'),
    secure = True,
)

STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'