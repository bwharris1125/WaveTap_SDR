import asyncio
import json
import logging
import math
import os
import threading

import pyModeS as pms
import websockets
from pyModeS.extra.tcpclient import TcpClient


class ADSBClient(TcpClient):
    """
    ADSBClient connects to a TCP source of ADS-B messages, decodes them,
    and maintains a rolling in-memory dictionary of aircraft data.
    """

    def __init__(self, host, port, data_type, receiver_lat: float | None = None, receiver_lon: float | None = None):
        super(ADSBClient, self).__init__(host, port, data_type)
        self.aircraft_data = {}
        self._cpr_states: dict[str, dict[str, tuple[str, float] | None]] = {}
        self._position_failures: dict[str, float] = {}
        self.receiver_lat = receiver_lat
        self.receiver_lon = receiver_lon
        logging.info(f"Starting ADSBClient on {host}:{port}[{data_type}]")

    def _update_position(self, icao: str, entry: dict, msg: str, timestamp: float) -> None:
        try:
            parity = pms.adsb.oe_flag(msg)
        except Exception:
            parity = None
        if parity is None:
            return

        state = self._cpr_states.setdefault(icao, {"even": None, "odd": None})
        key = "odd" if parity else "even"
        state[key] = (msg, timestamp)

        other_key = "even" if key == "odd" else "odd"
        other = state.get(other_key)
        if not other:
            return

        even = state.get("even")
        odd = state.get("odd")
        if not even or not odd:
            return

        msg_even, ts_even = even
        msg_odd, ts_odd = odd
        if abs(ts_even - ts_odd) > 10:
            last_log = self._position_failures.get(icao, 0.0)
            if timestamp - last_log > 30:
                logging.debug("Ignoring stale CPR pair for %s (delta %.1fs)", icao, abs(ts_even - ts_odd))
                self._position_failures[icao] = timestamp
            if key == "even":
                state["odd"] = None
            else:
                state["even"] = None
            return

        try:
            lat, lon = pms.adsb.position(msg_even, msg_odd, ts_even, ts_odd)
        except Exception:
            lat = lon = None
        if lat is None or lon is None:
            last_log = self._position_failures.get(icao, 0.0)
            if timestamp - last_log > 30:
                logging.debug("Failed to resolve CPR position for %s", icao)
                self._position_failures[icao] = timestamp
            return

        entry["position"] = {"lat": lat, "lon": lon}
        self._position_failures.pop(icao, None)
        self._annotate_distance(entry)

    def _annotate_distance(self, entry: dict) -> None:
        if self.receiver_lat is None or self.receiver_lon is None:
            entry.pop("distance_nm", None)
            entry.pop("distance_km", None)
            return
        position = entry.get("position")
        if not position:
            entry["distance_nm"] = None
            entry["distance_km"] = None
            return
        lat = position.get("lat")
        lon = position.get("lon")
        if lat is None or lon is None:
            entry["distance_nm"] = None
            entry["distance_km"] = None
            return
        distance_nm = self._haversine_nm(lat, lon, self.receiver_lat, self.receiver_lon)
        entry["distance_nm"] = distance_nm
        entry["distance_km"] = distance_nm * 1.852

    @staticmethod
    def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        radius_nm = 3440.065  # mean Earth radius in nautical miles
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return radius_nm * c

    def handle_messages(self, messages: list[tuple[str, float]]) -> None:
        """
        Parse a batch of ADS-B messages and update aircraft_data with decoded
        information. Stores to local dictionary in self.aircraft_data.
        """
        for msg, timestamp in messages:
            if len(msg) != 28:
                continue
            df = pms.df(msg)
            if pms.crc(msg) == 1:
                continue
            if df == 17:
                tc = pms.typecode(msg)
                icao = pms.icao(msg)
                if tc is None or icao is None:
                    continue
                # Initialize aircraft entry if not present
                if icao not in self.aircraft_data:
                    self.aircraft_data[icao] = {
                        "icao": icao,
                        "callsign": None,
                        "position": None,
                        "velocity": None,
                        "altitude": None,
                        "last_update": None,
                        "distance_nm": None,
                        "distance_km": None,
                        "first_seen": timestamp,
                    }
                entry = self.aircraft_data[icao]
                first_seen = entry.get("first_seen")
                if first_seen is None or timestamp < first_seen:
                    entry["first_seen"] = timestamp
                entry["last_update"] = timestamp
                if 1 <= tc <= 4:
                    entry["callsign"] = pms.adsb.callsign(msg)
                if 5 <= tc <= 8:
                    self._update_position(icao, entry, msg, timestamp)
                    entry["velocity"] = pms.adsb.surface_velocity(msg)
                if 9 <= tc <= 18:
                    alt = pms.adsb.altitude(msg)
                    entry["altitude"] = alt
                    self._update_position(icao, entry, msg, timestamp)
                if tc == 19:
                    velocity = pms.adsb.velocity(msg)
                    if velocity is not None:
                        entry["velocity"] = {
                            "speed": velocity[0],
                            "track": velocity[1],
                            "vertical_rate": velocity[2],
                            "type": velocity[3],
                        }
                # NOTE: Other typecodes can be added as needed
                # logging.debug(f"Updated aircraft {icao}") # extremely verbose


class ADSBPublisher:
    """
    ADSBPublisher manages a WebSocket server that periodically publishes
    processed ADS-B aircraft data from an ADSBClient to all connected clients.
    Handles clean startup and shutdown for microservice integration.
    """
    def __init__(self, host, src_port=30002, dest_ip="0.0.0.0", dest_port=8443, interval=3, receiver_lat: float | None = None, receiver_lon: float | None = None):
        self.dest_ip = dest_ip
        self.dest_port = dest_port
        self.interval = interval
        self.src_client = ADSBClient(host, src_port, "raw", receiver_lat=receiver_lat, receiver_lon=receiver_lon)
        self.clients = set()
        self._client_thread = None
        self._shutdown_event = threading.Event()
        self.bound_port = None
        logging.info("Starting ADSBPublisher...")

    async def handler(self, websocket) -> None:
        """
        Handle a new WebSocket client connection and remove it on disconnect.
        """
        self.clients.add(websocket)
        try:
            await websocket.wait_closed()
        finally:
            self.clients.remove(websocket)

    async def publish_data(self) -> None:
        """
        Periodically publish the current aircraft data to all connected
        WebSocket clients.
        """
        while True:
            if self.clients:
                data = json.dumps(self.src_client.aircraft_data, default=str)
                await asyncio.gather(*[ws.send(data) for ws in self.clients])
            await asyncio.sleep(self.interval)

    async def run(self) -> None:
        """
        Start the ADSB client in a thread and run the WebSocket server for
        publishing data.
        """
        # Start ADSB client in a thread
        self._client_thread = threading.Thread(target=self.src_client.run, daemon=True)
        self._client_thread.start()
        # Start WebSocket server
        async with websockets.serve(self.handler, self.dest_ip, self.dest_port) as server:
            sockets = getattr(server, "sockets", None)
            if sockets:
                try:
                    self.bound_port = sockets[0].getsockname()[1]
                except (IndexError, OSError):
                    self.bound_port = self.dest_port
            else:
                self.bound_port = self.dest_port
            await self.publish_data()

    # NOTE: not currently captured by `ctrl+c` due to async structure
    async def close(self) -> None:
        """
        Cleanly shut down the publisher, closing all WebSocket clients and
        stopping the ADSB client thread.
        """
        logging.info("Shutting down ADSBPublisher...")
        # Signal shutdown to any loops/threads
        self._shutdown_event.set()
        # Close all websocket clients
        for ws in list(self.clients):
            await ws.close()
        # Optionally join the client thread if needed
        if self._client_thread and self._client_thread.is_alive():
            self._client_thread.join(timeout=2)


def _env_float(name: str, default: float | None = None) -> float | None:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        logging.warning("Invalid float for %s=%s; using default %s", name, value, default)
        return default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logging.warning("Invalid int for %s=%s; using default %s", name, value, default)
        return default


def _load_config_from_env() -> dict[str, float | int | str | None]:
    return {
        "host": os.getenv("DUMP1090_HOST", "192.168.50.106"), # TODO: change to dynamic
        "src_port": _env_int("DUMP1090_RAW_PORT", 30002),
        "dest_ip": os.getenv("ADSB_WS_HOST", "0.0.0.0"),
        "dest_port": _env_int("ADSB_WS_PORT", 8443),
        "interval": _env_float("ADSB_PUBLISH_INTERVAL", 3.0) or 3.0,
        "receiver_lat": _env_float("RECEIVER_LAT"),
        "receiver_lon": _env_float("RECEIVER_LON"),
    }


async def main():
    config = _load_config_from_env()
    publisher = ADSBPublisher(
        host=config["host"],
        src_port=config["src_port"],
        dest_ip=config["dest_ip"],
        dest_port=config["dest_port"],
        interval=config["interval"],
        receiver_lat=config["receiver_lat"],
        receiver_lon=config["receiver_lon"],
    )
    try:
        await publisher.run()
    except KeyboardInterrupt:
        # FIXME needs additional infrastructure due to async
        logging.info("KeyboardInterrupt received, shutting down...")
        await publisher.close()


if __name__ == "__main__":
    log_level = os.getenv("ADSB_PUBLISHER_LOG_LEVEL", "DEBUG").upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.DEBUG))
    asyncio.run(main())