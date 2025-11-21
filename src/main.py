"""WaveTap orchestration bootstrap.

ONLY USE WHEN TESTING LOCALLY FOR EASE OF DEVELOPMENT

This OPTIONAL module emulates the eventual microservice deployment of the WaveTap
platform by spinning up each component in its own thread:

* ADS-B publisher (SDR capture): streams decoded dump1090 traffic over WebSocket
* ADS-B subscriber (database API backend): mirrors live traffic into SQLite
* WaveTap Flask API: presents dashboards and routes backed by the shared DB

The design mirrors the production layout where each piece will live in its own
container. Running ``python -m main`` locally now brings up the whole stack so
developers can iterate quickly while documenting the moving parts in code.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Optional

BASE_DIR = Path(__file__).resolve().parent
DATABASE_API_DIR = BASE_DIR / "database_api"
SDR_CAP_DIR = BASE_DIR / "sdr_cap"

for directory in (DATABASE_API_DIR, SDR_CAP_DIR):
    path_str = str(directory)
    if directory.exists() and path_str not in sys.path:
        sys.path.append(path_str)

from werkzeug.serving import make_server  # noqa: E402

from database_api.adsb_subscriber import ADSBSubscriber  # noqa: E402
from database_api.wavetap_api import app as flask_app  # noqa: E402
from sdr_cap.adsb_publisher import ADSBPublisher  # noqa: E402

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(threadName)s - %(message)s"
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublisherSettings:
    """Connection details for the ADS-B publisher microservice."""

    dump1090_host: str
    dump1090_port: int
    websocket_host: str
    websocket_port: int
    publish_interval: float
    receiver_lat: Optional[float]
    receiver_lon: Optional[float]


@dataclass(frozen=True)
class SubscriberSettings:
    """Parameters for subscribing to the publisher and persisting to SQLite."""

    websocket_uri: str
    db_path: Optional[str]
    save_interval: float


@dataclass(frozen=True)
class ApiSettings:
    """Settings for the Flask control center."""

    host: str
    port: int
    debug: bool
    threaded: bool


@dataclass(frozen=True)
class WaveTapConfig:
    """Aggregate configuration for all WaveTap services."""

    publisher: PublisherSettings
    subscriber: SubscriberSettings
    api: ApiSettings


@dataclass(frozen=True)
class ServiceDefinition:
    """Metadata describing a managed service."""

    name: str
    description: str
    runner: Callable[[WaveTapConfig, threading.Event, threading.Event], None]


@dataclass
class ServiceHandle:
    name: str
    description: str
    thread: threading.Thread
    ready: threading.Event


def _env_float(name: str) -> Optional[float]:
    value = os.getenv(name)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        LOGGER.warning("Ignoring invalid float for %s: %s", name, value)
        return None


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        LOGGER.warning("Ignoring invalid int for %s: %s", name, value)
        return default


def _env_float_with_default(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        LOGGER.warning("Ignoring invalid float for %s: %s", name, value)
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def load_config() -> WaveTapConfig:
    """Derive configuration for each managed service from environment."""

    dump1090_host = os.getenv("DUMP1090_HOST", "192.168.50.106") # this is specific to my development setup
    dump1090_port = _env_int("DUMP1090_RAW_PORT", 30002)
    websocket_host = os.getenv("ADSB_WS_HOST", "0.0.0.0")
    websocket_port = _env_int("ADSB_WS_PORT", 8443)
    publish_interval = _env_float_with_default("ADSB_PUBLISH_INTERVAL", 3.0)
    receiver_lat = _env_float("RECEIVER_LAT")
    receiver_lon = _env_float("RECEIVER_LON")

    default_ws_uri = f"ws://127.0.0.1:{websocket_port}"
    websocket_uri = os.getenv("ADSB_WS_URI", default_ws_uri)
    db_path_env = os.getenv("ADSB_DB_PATH")
    save_interval = _env_float_with_default("ADSB_SAVE_INTERVAL", 10.0)

    api_host = os.getenv("WAVETAP_API_HOST", "0.0.0.0")
    api_port = _env_int("WAVETAP_API_PORT", 5000)
    api_debug = _env_bool("WAVETAP_API_DEBUG", False)
    api_threaded = _env_bool("WAVETAP_API_THREADED", True)

    publisher_cfg = PublisherSettings(
        dump1090_host=dump1090_host,
        dump1090_port=dump1090_port,
        websocket_host=websocket_host,
        websocket_port=websocket_port,
        publish_interval=publish_interval,
        receiver_lat=receiver_lat,
        receiver_lon=receiver_lon,
    )

    subscriber_cfg = SubscriberSettings(
        websocket_uri=websocket_uri,
        db_path=db_path_env,
        save_interval=save_interval,
    )

    api_cfg = ApiSettings(
        host=api_host,
        port=api_port,
        debug=api_debug,
        threaded=api_threaded,
    )

    return WaveTapConfig(
        publisher=publisher_cfg,
        subscriber=subscriber_cfg,
        api=api_cfg,
    )


def run_adsb_publisher_service(
    config: WaveTapConfig,
    ready: threading.Event,
    stop_event: threading.Event,
) -> None:
    """Launch the ADS-B publisher loop in its own asyncio event loop."""

    settings = config.publisher
    publisher = ADSBPublisher(
        host=settings.dump1090_host,
        src_port=settings.dump1090_port,
        dest_ip=settings.websocket_host,
        dest_port=settings.websocket_port,
        interval=settings.publish_interval,
        receiver_lat=settings.receiver_lat,
        receiver_lon=settings.receiver_lon,
    )

    async def _runner() -> None:
        LOGGER.info(
            "ADS-B publisher connecting to dump1090 at %s:%s and serving ws://%s:%s",
            settings.dump1090_host,
            settings.dump1090_port,
            settings.websocket_host,
            settings.websocket_port,
        )
        publish_task = asyncio.create_task(publisher.run())
        ready.set()
        try:
            while not stop_event.is_set():
                await asyncio.sleep(0.5)
        finally:
            publish_task.cancel()
            with suppress(asyncio.CancelledError):
                await publish_task
            with suppress(Exception):
                await publisher.close()

    asyncio.run(_runner())


def run_adsb_subscriber_service(
    config: WaveTapConfig,
    ready: threading.Event,
    stop_event: threading.Event,
) -> None:
    """Start the ADS-B subscriber responsible for database persistence."""

    settings = config.subscriber
    subscriber = ADSBSubscriber(settings.websocket_uri)
    subscriber.setup_db(settings.db_path)

    async def _periodic_saver() -> None:
        while not stop_event.is_set():
            await subscriber.save_to_db()
            await asyncio.sleep(settings.save_interval)

    async def _runner() -> None:
        LOGGER.info("ADS-B subscriber consuming %s and persisting to %s", settings.websocket_uri, settings.db_path)
        listen_task = asyncio.create_task(subscriber.connect_and_listen())
        save_task = asyncio.create_task(_periodic_saver())
        ready.set()
        try:
            while not stop_event.is_set():
                await asyncio.sleep(0.5)
        finally:
            for task in (listen_task, save_task):
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            if subscriber.db_worker is not None:
                subscriber.db_worker.stop()
                subscriber.db_worker.join(timeout=2)

    asyncio.run(_runner())


def run_api_service(
    config: WaveTapConfig,
    ready: threading.Event,
    stop_event: threading.Event,
) -> None:
    """Expose the WaveTap control center through Flask's development server."""

    settings = config.api
    db_path = config.subscriber.db_path
    if db_path:
        flask_app.config["ADSB_DB_PATH"] = db_path

    server = make_server(
        settings.host,
        settings.port,
        flask_app,
        threaded=settings.threaded,
    )
    server.timeout = 1
    ready.set()
    LOGGER.info("WaveTap API available at http://%s:%s", settings.host or "127.0.0.1", settings.port)

    try:
        while not stop_event.is_set():
            server.handle_request()
    finally:
        with suppress(Exception):
            server.server_close()


SERVICE_DEFINITIONS: list[ServiceDefinition] = [
    ServiceDefinition(
        name="ADS-B Publisher",
        description="Connects to dump1090 and republishes aircraft telemetry via WebSocket.",
        runner=run_adsb_publisher_service,
    ),
    ServiceDefinition(
        name="ADS-B Subscriber",
        description="Consumes the WebSocket stream, maintains in-memory state, and persists to SQLite.",
        runner=run_adsb_subscriber_service,
    ),
    ServiceDefinition(
        name="WaveTap API",
        description="Flask control center exposing dashboards and REST endpoints for ADS-B data.",
        runner=run_api_service,
    ),
]


class WaveTapRuntime:
    """Coordinator that manages service threads and shared shutdown state."""

    def __init__(self, config: WaveTapConfig):
        self.config = config
        self.stop_event = threading.Event()
        self.services: list[ServiceHandle] = []
        self.publisher = None
        self.subscriber = None

    def start_all(self) -> None:
        """Spin up each managed service in its own daemon thread."""

        for definition in SERVICE_DEFINITIONS:
            ready = threading.Event()

            thread = threading.Thread(
                target=self._service_wrapper,
                name=f"{definition.name.replace(' ', '')}Thread",
                args=(definition, ready),
                daemon=True,
            )
            thread.start()
            self.services.append(ServiceHandle(
                name=definition.name,
                description=definition.description,
                thread=thread,
                ready=ready,
            ))

        for handle in self.services:
            handle.ready.wait()
        LOGGER.info("All services signaled ready. WaveTap stack is live.")

    def _service_wrapper(self, definition: ServiceDefinition, ready: threading.Event) -> None:
        try:
            definition.runner(self.config, ready, self.stop_event)
        except Exception:  # pragma: no cover - defensive logging
            LOGGER.exception("Service %s crashed; signalling shutdown", definition.name)
            ready.set()
            self.stop_event.set()

    def block_forever(self) -> None:
        """Keep the main thread alive until interrupted, mirroring production."""

        try:
            while not self.stop_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            LOGGER.info("KeyboardInterrupt received; beginning shutdown...")
            self.stop_all()

    def stop_all(self) -> None:
        """Signal every service to shut down and wait for threads to exit."""

        if not self.stop_event.is_set():
            self.stop_event.set()
        for handle in self.services:
            if handle.thread.is_alive():
                handle.thread.join(timeout=5)
        LOGGER.info("All services stopped.")
        self._export_metrics_on_shutdown()

    def describe_services(self) -> str:
        """Return a multi-line human-readable service overview."""

        lines = ["WaveTap runtime will start the following components:"]
        if self.services:
            iterable = self.services
        else:
            iterable = [SimpleNamespace(name=d.name, description=d.description) for d in SERVICE_DEFINITIONS]
        for handle in iterable:
            lines.append(f" - {handle.name}: {handle.description}")
        return "\n".join(lines)

    def _export_metrics_on_shutdown(self) -> None:
        """
        Export collected metrics to JSON files upon shutdown.

        Attempts to export TCP metrics from the global collector to timestamped
        JSON files in the current directory or a specified output directory.
        """
        try:
            from utilities.metrics import get_tcp_collector

            collector = get_tcp_collector()
            if not collector or not collector.get_history():
                LOGGER.debug("No metrics to export")
                return

            # Create metrics directory if it doesn't exist
            metrics_dir = Path.cwd() / "metrics"
            metrics_dir.mkdir(exist_ok=True)

            # Generate timestamped filename
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            metrics_file = metrics_dir / f"tcp_metrics_{timestamp}.json"

            # Export metrics
            collector.export_to_json(str(metrics_file))
            LOGGER.info("Metrics exported to %s", metrics_file)

        except ImportError:
            LOGGER.debug("Metrics module not available for export")
        except Exception as e:
            LOGGER.warning("Failed to export metrics: %s", e)


def configure_logging() -> None:
    level_name = os.getenv("WAVETAP_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format=LOG_FORMAT)


def main(run_forever: bool = True) -> WaveTapRuntime:
    """Entrypoint that wires up the in-process microservice emulation."""

    configure_logging()
    config = load_config()
    runtime = WaveTapRuntime(config)
    LOGGER.info(runtime.describe_services())
    runtime.start_all()
    if run_forever:
        runtime.block_forever()
    return runtime


if __name__ == "__main__":
    main(run_forever=True)
