# WaveTap SDR capture (ADS-B publisher)
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

COPY src/sdr_cap/ ${APP_HOME}/sdr_cap/

ENV PYTHONPATH=${APP_HOME} \
    DUMP1090_HOST=127.0.0.1 \
    DUMP1090_RAW_PORT=30002 \
    ADSB_WS_HOST=0.0.0.0 \
    ADSB_WS_PORT=8443 \
    ADSB_PUBLISH_INTERVAL=3

EXPOSE 8443

ENTRYPOINT ["python", "-m", "sdr_cap.adsb_publisher"]
