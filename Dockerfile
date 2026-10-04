# ===================================================================
#  Personal Fitness Tracker - container image
#
#  Built on the Raspberry Pi by deploy-to-pi.bat (or manually with
#  `docker compose build`).
#
#  Data (the SQLite database and any imported files) is NOT baked into the
#  image. It lives in the ./data folder on the Pi, mounted at /app/data,
#  so rebuilding the container never loses data.
#
#  Note on the user account: the container deliberately runs as root.
#  The database is a file on a bind mount owned by your Pi user, and the Pi
#  account's uid is not guaranteed to match anything baked into the image -
#  running as root is the only setting that is guaranteed to be able to
#  write ./data. To run as a non-root user instead, uncomment the `user:`
#  line in docker-compose.yml and set it to your Pi uid:gid.
# ===================================================================
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so code-only changes reuse this layer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY fitness_app /app/fitness_app

# Scripts (db_tool.py, import_data.py) - needed by cron jobs running in the container
COPY scripts /app/scripts

# Data folder must exist before the bind mount is attached
RUN mkdir -p /app/data

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FITNESS_HOST=0.0.0.0 \
    FITNESS_PORT=5000 \
    FITNESS_DEBUG=0

EXPOSE 5000

CMD ["python", "-m", "fitness_app"]
