import asyncio
import json
import logging
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import websockets
from websockets import exceptions as ws_exc

from database_api.adsb_db import DBWorker
from wavetap_utils.network_metrics import get_network_collector


class ADSBSubscriber:
    """Subscribe to ADS-B updates, mirror them locally, and persist into SQLite."""

    def __init__(self, uri: str):
        """Initialize the subscriber with the WebSocket URI."""
        self.uri = uri
        self.aircraft_data = {}
        self.db_worker = None
        self.active_sessions = {}
        self.last_saved_ts = {}
        self.metrics_collector = get_network_collector()

    def setup_db(self, db_path=None):
        """Initialize DBWorker for database operations."""
        if db_path is None:
            env_path = os.environ.get("ADSB_DB_PATH")
            if env_path:
                db_path = env_path
            else:
                db_path = str(Path(__file__).with_name("adsb_data.db"))
        self.db_worker = DBWorker(db_path)
        self.db_worker.start()
        self.active_sessions = {}
        self.last_saved_ts = {}

    async def connect_and_listen(self, retry_delay: float = 5.0, max_retry_delay: float = 60.0):
        """
        Connect to the WebSocket publisher and update aircraft_data as new
        data arrives.
        # TODO HANDLE FAILED CONNECTIONS AND DISCONNECTIONS GRACEFULLY
        """
        base_delay = max(retry_delay, 0.1)
        delay = base_delay
        while True:
            connected = False
            try:
                async with websockets.connect(self.uri) as ws:
                    logging.info("Connected to publisher at %s", self.uri)
                    connected = True
                    delay = base_delay
                    while True:
                        try:
                            data = await ws.recv()
                        except asyncio.CancelledError:
                            raise
                        except ws_exc.ConnectionClosed as exc:
                            logging.warning(
                                "Connection to %s closed (%s); retrying in %.1fs",
                                self.uri,
                                getattr(exc, "reason", exc),
                                delay,
                            )
                            break
                        try:
                            received = json.loads(data)
                            # Record network metric for each message received
                            self.metrics_collector.record_packet()
                            if isinstance(received, dict):
                                self.aircraft_data = received
                                logging.debug(
                                    "Updated aircraft_data with %d entries.",
                                    len(received),
                                )
                            else:
                                logging.warning(
                                    "Received non-dict data: %s",
                                    type(received),
                                )
                        except Exception as exc:
                            # Record failed message as dropped packet
                            self.metrics_collector.record_dropped_packet()
                            logging.warning("Failed to decode message: %s", exc)
            except asyncio.CancelledError:
                raise
            except (OSError, ws_exc.WebSocketException) as exc:
                logging.warning(
                    "Unable to connect to publisher at %s: %s; retrying in %.1fs",
                    self.uri,
                    exc,
                    delay,
                )
            await asyncio.sleep(delay)
            if connected:
                delay = base_delay
            else:
                delay = min(delay * 2, max(max_retry_delay, base_delay))

    # TODO write to database
    async def save_to_db(self):
        """
        Save current aircraft_data to the database, including velocity fields and session tracking.
        """
        if self.db_worker is None:
            logging.warning("DB worker not initialized; call setup_db() before saving data.")
            return
        if not self.aircraft_data:
            logging.debug("No aircraft data to save to database.")
            return
        for icao, entry in self.aircraft_data.items():
            last_update = entry.get("last_update")
            logging.debug("Saving aircraft %s to database: %s", icao, entry)
            self.db_worker.enqueue((
                "upsert_aircraft",
                icao,
                entry.get("callsign"),
                entry.get("first_seen"),
                last_update,
                entry.get("assembly_time_ms"),
                entry.get("stale_cpr_count"),
            ))
            if last_update is None:
                continue

            previous_ts = self.last_saved_ts.get(icao)
            if previous_ts is not None and last_update <= previous_ts:
                logging.debug(
                    "Skipping duplicate position for %s (last_update=%s, previous=%s)",
                    icao,
                    last_update,
                    previous_ts,
                )
                continue

            self.last_saved_ts[icao] = last_update

            session_id = self.active_sessions.get(icao)
            if not session_id:
                session_id = str(uuid.uuid4())
                self.active_sessions[icao] = session_id
                self.db_worker.enqueue((
                    "start_session",
                    session_id,
                    icao,
                    last_update,
                ))

            position = entry.get("position") or {}
            if not position:
                continue

            velocity = entry.get("velocity") or {}
            ts_iso = datetime.fromtimestamp(last_update, UTC).isoformat()
            self.db_worker.enqueue((
                "insert_path",
                session_id,
                icao,
                last_update,
                ts_iso,
                position.get("lat"),
                position.get("lon"),
                entry.get("altitude"),
                velocity.get("speed"),
                velocity.get("track"),
                velocity.get("vertical_rate"),
                velocity.get("type"),
            ))
            logging.debug("Inserted path for %s at %s", icao, ts_iso)


def print_aircraft_data(collector, interval: int = 3) -> None:
    last_lines = 0
    while True:
        # Table header
        header = (
            f"{'ICAO':<8} {'CALLSIGN':<10} "
            f"{'LAT':>10} {'LON':>10} {'ALT':>8}"
        )
        output_lines = [header]
        # Table rows
        for icao, entry in collector.aircraft_data.items():
            callsign = str(entry.get("callsign", ""))
            position = entry.get("position", {})
            altitude = str(entry.get("altitude", ""))
            lat = f"{position.get('lat', ''):.5f}" if position and position.get("lat") is not None else ""
            lon = f"{position.get('lon', ''):.5f}" if position and position.get("lon") is not None else ""
            output_lines.append(f"{icao:<8} {callsign:<10} {lat:>10} {lon:>10} {altitude:>8}")
        # Move cursor up to overwrite previous output
        if last_lines:
            sys.stdout.write(f"\033[{last_lines}F")
        # Write all lines, each followed by a single newline
        for line in output_lines:
            sys.stdout.write(line + "\n")
        # If fewer lines than last time, clear remaining
        extra_lines = last_lines - len(output_lines)
        if extra_lines > 0:
            sys.stdout.write((' ' * 80 + '\n') * extra_lines)
        sys.stdout.flush()
        last_lines = len(output_lines)
        time.sleep(interval)


async def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="ADS-B Subscriber Service"
    )
    parser.add_argument(
        "--uri",
        type=str,
        default=os.environ.get("ADSB_WS_URI", "ws://127.0.0.1:8443"),
        help="WebSocket URI for publisher"
    )
    default_db = os.environ.get("ADSB_DB_PATH") or str(Path(__file__).with_name("adsb_data.db"))
    parser.add_argument(
        "--db",
        type=str,
        default=default_db,
        help="Path to SQLite database file"
    )
    args = parser.parse_args()

    subscriber = ADSBSubscriber(args.uri)
    subscriber.setup_db(args.db)

    # Start network metrics collection
    subscriber.metrics_collector.start_csv_logging()
    subscriber.metrics_collector.start_periodic_logging(interval_seconds=10.0)
    logging.info("Network metrics collection started")

    async def periodic_db_save():
        while True:
            await subscriber.save_to_db()
            await asyncio.sleep(10)

    await asyncio.gather(
        subscriber.connect_and_listen(),
        periodic_db_save()
    )


if __name__ == "__main__":
    log_dir = os.environ.get("ADSB_LOG_DIR", "tmp/logs")
    log_level = os.environ.get("ADSB_SUBSCRIBER_LOG_LEVEL", "DEBUG")

    # Import logging config after os is available
    from wavetap_utils.logging_config import setup_component_logging
    setup_component_logging("subscriber", log_level=log_level, log_dir=log_dir)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Subscriber stopped by user.")
    finally:
        # Cleanup network metrics
        try:
            metrics_collector = get_network_collector()
            metrics_collector.stop_periodic_logging()
            metrics_collector.stop_csv_logging()
            logging.info("Network metrics collection stopped")
        except Exception as e:
            logging.error("Error stopping metrics: %s", e)