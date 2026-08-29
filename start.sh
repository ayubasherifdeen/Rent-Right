#!/bin/bash
set -e

echo "Running migrations..."
python manage.py migrate --noinput

echo "Creating superuser if needed..."
DJANGO_SUPERUSER_USERNAME="$DJANGO_SUPERUSER_USERNAME" \
DJANGO_SUPERUSER_EMAIL="$DJANGO_SUPERUSER_EMAIL" \
DJANGO_SUPERUSER_PASSWORD="$DJANGO_SUPERUSER_PASSWORD" \
python manage.py createsuperuser --noinput || true

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Gunicorn..."
exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000}