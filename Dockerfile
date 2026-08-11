# Jooble Listings — Dash app, containerized for Google Cloud Run.
#
# Cloud Run injects a $PORT env var (8080 by default) and routes traffic to it.
# gunicorn serves the Dash WSGI app, which app.py exposes as `server = app.server`.
FROM python:3.12-slim

# Unbuffered logs (so they show up in Cloud Logging), no .pyc clutter.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Install dependencies first so this layer is cached across code-only changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY . .

# Documentation only; Cloud Run uses $PORT regardless.
EXPOSE 8080

# `exec` makes gunicorn PID 1 so it receives Cloud Run's SIGTERM on shutdown.
# Shell form is used so $PORT expands at runtime. --timeout covers the longest
# synchronous request (a Jooble fetch paginates + retries server-side).
CMD exec gunicorn --bind :$PORT --workers 2 --threads 4 --timeout 120 app:server
