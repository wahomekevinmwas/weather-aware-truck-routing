#!/usr/bin/env bash
# Render build: install Python deps, build the React app, collect Django static files, create tables.
set -o errexit
pip install -r backend/requirements.txt
cd frontend
npm ci
npm run build
cd ../backend
python manage.py collectstatic --noinput
python manage.py migrate --noinput
