#!/bin/sh
set -e

# Before migrate: collecting static touches no database, so a new stylesheet still
# lands even if the DB is slow to come up. STATIC_ROOT is the ./static bind mount,
# which nginx serves — without this step a deploy ships new CSS/JS that nobody sees.
# No --clear: that would empty the directory first and blank the admin mid-deploy.
python manage.py collectstatic --noinput
python manage.py migrate --noinput
exec uvicorn core.asgi:application --host 0.0.0.0 --port 8000 --workers 4
