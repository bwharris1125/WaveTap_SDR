import asyncio
import json
import logging
import sys
import time
import uuid

import websockets

from database.adsb_db import DBWorker


class ADSBSubscriber:
    def setup_db(self, db_path="src/database/adsb.db"):
        """Initialize DBWorker for database operations."""
        self.db_worker = DBWorker(db_path)
        self.db_worker.start()
        self.active_sessions = {}  # {icao: session_id}
    """
    ADSBSubscriber connects to a WebSocket publisher, receives ADS-B aircraft
    data, and maintains a rolling in-memory dictionary of aircraft data on the
    subscriber side.
    """
    def __init__(self, uri: str):
        """
        Initialize the subscriber with the WebSocket URI.
        """
        self.uri = uri
        self.aircraft_data = {}

    async def connect_and_listen(self):
        """
        Connect to the WebSocket publisher and update aircraft_data as new
        data arrives.
        # TODO HANDLE FAILED CONNECTIONS AND DISCONNECTIONS GRACEFULLY
        """
        async with websockets.connect(self.uri) as ws:
            logging.info(f"Connected to publisher at {self.uri}")
            while True:
                data = await ws.recv()
                try:
                    received = json.loads(data)
                    if isinstance(received, dict):
                        self.aircraft_data = received
                        logging.debug(f"Updated aircraft_data with {len(received)} entries.")
                except Exception as e:
                    logging.warning(f"Failed to decode message: {e}")

    # TODO write to database
    async def save_to_db(self):
        """
        Save current aircraft_data to the database, including velocity fields and session tracking.
        """
        for icao, entry in self.aircraft_data.items():
            # Save to aircraft table
            self.db_worker.enqueue((
                "upsert_aircraft",
                icao,
                entry.get("callsign"),
                entry.get("first_seen"),
                entry.get("last_update")
            ))
            # Session tracking
            session_id = self.active_sessions.get(icao)
            if not session_id:
                session_id = str(uuid.uuid4())
                self.active_sessions[icao] = session_id
                self.db_worker.enqueue((
                    "start_session",
                    session_id,
                    icao,
                    entry.get("last_update")
                ))
            else:
                self.db_worker.enqueue((
                    "end_session",
                    session_id,
                    entry.get("last_update")
                ))
            # Save to path table
            position = entry.get("position")
            velocity = entry.get("velocity")
            if position:
                # Compose ts_iso if needed
                ts = entry.get("last_update")
                import datetime
                ts_iso = datetime.datetime.utcfromtimestamp(ts).isoformat() if ts else None
                self.db_worker.enqueue((
                    "insert_path",
                    session_id,
                    icao,
                    ts,
                    ts_iso,
                    position.get("lat"),
                    position.get("lon"),
                    entry.get("altitude"),
                    velocity.get("speed") if velocity else None,
                    velocity.get("track") if velocity else None,
                    velocity.get("vertical_rate") if velocity else None,
                    velocity.get("type") if velocity else None
                ))


def print_aircraft_data(collector, interval: int = 3) -> None:
    last_lines = 0
    while True:
        # Table header
        header = f"{'ICAO':<8} {'CALLSIGN':<10} {'LAT':>10} {'LON':>10} {'ALT':>8}"
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
    uri = "ws://127.0.0.1:8443" # TODO make configurable
    subscriber = ADSBSubscriber(uri)
    subscriber.setup_db("adsb.db")
    async def periodic_db_save():
        while True:
            await subscriber.save_to_db()
            await asyncio.sleep(10)
    await asyncio.gather(
        subscriber.connect_and_listen(),
        periodic_db_save()
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
