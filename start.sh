#!/bin/bash
set -e

if [ -n "${RAILWAY_ENVIRONMENT:-}" ] || [ -n "${PORT:-}" ] || [ -n "${DYNO:-}" ]; then
  export DJANGO_SETTINGS_MODULE="config.settings.production"
fi

if [ -z "${DJANGO_SETTINGS_MODULE:-}" ]; then
  export DJANGO_SETTINGS_MODULE="config.settings.development"
fi

echo "Using Django settings: ${DJANGO_SETTINGS_MODULE}"
echo "Running migrations..."
python manage.py migrate --noinput

echo "Creating superuser if needed..."
DJANGO_SUPERUSER_FIST_NAME="$DJANGO_SUPERUSER_FIST_NAME" \
  DJANGO_SUPERUSER_LAST_NAME="$DJANGO_SUPERUSER_LAST_NAME" \
  DJANGO_SUPERUSER_USERNAME="$DJANGO_SUPERUSER_USERNAME" \
  DJANGO_SUPERUSER_EMAIL="$DJANGO_SUPERUSER_EMAIL" \
  DJANGO_SUPERUSER_PASSWORD="$DJANGO_SUPERUSER_PASSWORD" \
  python manage.py createsuperuser --noinput || true

echo "Building Tailwind CSS..."
python manage.py tailwind build

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Gunicorn..."
exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000}