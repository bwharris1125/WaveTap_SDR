# WaveTap database API base image
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOME=/app \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR ${APP_HOME}

# Install build dependencies for wheels that require compilation
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        build-essential \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first to leverage Docker layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy API sources
COPY src/database_api/ ${APP_HOME}/

# Runtime environment
ENV PYTHONPATH=${APP_HOME} \
    FLASK_APP=wavetap_api:app \
    ADSB_DB_PATH=/data/adsb_data.db

# Create mount point for persistent database files
VOLUME ["/data"]

EXPOSE 5000

# Default command spins up Gunicorn; override in docker-compose for subscriber worker
ENTRYPOINT ["gunicorn"]
CMD ["--bind", "0.0.0.0:5000", "wavetap_api:app"]
