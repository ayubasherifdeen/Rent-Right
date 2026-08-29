#!/bin/bash
set -e

# Run Django migrations
python manage.py migrate --noinput
#create superuser
DJANGO_SUPERUSER_USERNAME=$DJANGO_SUPERUSER_USERNAME \
DJANGO_SUPERUSER_EMAIL=$DJANGO_SUPERUSER_EMAIL \
DJANGO_SUPERUSER_PASSWORD=$DJANGO_SUPERUSER_PASSWORD \
python manage.py createsuperuser --noinput || true  

# Collect static files
python manage.py collectstatic --noinput

# Start gunicorn
gunicorn rent_management.wsgi --bind 0.0.0.0:${PORT:-8000}
