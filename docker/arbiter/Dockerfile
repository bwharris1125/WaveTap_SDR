# WaveTap arbiter management service
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOME=/app \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR ${APP_HOME}

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        build-essential \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/arbiter/ ${APP_HOME}/arbiter/

ENV PYTHONPATH=${APP_HOME}

EXPOSE 8000

ENTRYPOINT ["uvicorn", "arbiter.service:app", "--host", "0.0.0.0", "--port", "8000"]
