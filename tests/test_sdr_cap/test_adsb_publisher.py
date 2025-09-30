import asyncio
import json
import threading
from types import SimpleNamespace

import pytest
import websockets

from sdr_cap import adsb_publisher
from sdr_cap.adsb_publisher import ADSBPublisher

HOST = "127.0.0.1"
SRC_PORT = 30002
DEST_PORT = 0

def test_adsb_publisher_receives(monkeypatch):
    async def scenario():
        # Mock ADSBClient to provide predictable data
        class MockClient:
            aircraft_data = {"TEST123": {"callsign": "TEST", "altitude": 10000, "position": {"lat": 51.0, "lon": -0.1}}}

            def run(self):
                pass

        # Patch ADSBPublisher to use MockClient
        monkeypatch.setattr(
            "sdr_cap.adsb_publisher.ADSBClient",
            lambda host, port, dtype, **kwargs: MockClient(),
        )
        publisher = ADSBPublisher(HOST, SRC_PORT, HOST, DEST_PORT, interval=0.1)

        async def run_publisher():
            await publisher.run()

        # Start publisher in background
        task = asyncio.create_task(run_publisher())
        # Wait for server to bind to a random port
        for _ in range(20):
            if publisher.bound_port:
                break
            await asyncio.sleep(0.05)
        assert publisher.bound_port, "Publisher did not bind to a port"

        # Connect as a websocket client
        uri = f"ws://{HOST}:{publisher.bound_port}"
        async with websockets.connect(uri) as ws:
            data = await ws.recv()
            decoded = json.loads(data)
            assert "TEST123" in decoded
            assert decoded["TEST123"]["callsign"] == "TEST"
            assert decoded["TEST123"]["altitude"] == 10000
            assert decoded["TEST123"]["position"]["lat"] == 51.0
            assert decoded["TEST123"]["position"]["lon"] == -0.1

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())


def test_adsb_client_handle_messages(monkeypatch):
    client = adsb_publisher.ADSBClient.__new__(adsb_publisher.ADSBClient)
    client.aircraft_data = {}
    client._cpr_states = {}
    client._position_failures = {}
    client.receiver_lat = 33.0
    client.receiver_lon = -97.0

    def fake_df(msg):
        return 17

    def fake_crc(msg):
        return 0

    type_map = {
        "CALLSIGN": 2,
        "SURFACE": 6,
        "ALTITUDE": 10,
        "VELOCITY": 19,
    }

    def fake_typecode(msg):
        return type_map.get(msg.strip(), 0)

    monkeypatch.setattr(adsb_publisher.pms, "df", fake_df)
    monkeypatch.setattr(adsb_publisher.pms, "crc", fake_crc)
    monkeypatch.setattr(adsb_publisher.pms, "typecode", fake_typecode)
    monkeypatch.setattr(adsb_publisher.pms, "icao", lambda msg: "ABC123")

    fake_adsb = SimpleNamespace(
        callsign=lambda msg: "TEST123",
        surface_velocity=lambda msg: {
            "speed": 15,
            "track": 270,
            "vertical_rate": -5,
            "type": "surface",
        },
        altitude=lambda msg: 18500,
        velocity=lambda msg: (255, 90, 0, "airborne"),
        oe_flag=lambda msg: 0 if msg.strip() == "SURFACE" else 1,
        position=lambda even_msg, odd_msg, te, to: (33.0001, -96.9999),
    )
    fake_common = SimpleNamespace(
        hex2bin=lambda msg: "0" * 112,
        bin2int=lambda bits: 65536,
    )
    monkeypatch.setattr(adsb_publisher.pms, "adsb", fake_adsb)
    monkeypatch.setattr(adsb_publisher.pms, "common", fake_common)

    messages = [
        ("SHORT", 1000.0),
        ("CALLSIGN".ljust(28), 1001.0),
        ("SURFACE".ljust(28), 1002.0),
        ("ALTITUDE".ljust(28), 1003.0),
        ("VELOCITY".ljust(28), 1004.0),
    ]

    client.handle_messages(messages)

    entry = client.aircraft_data["ABC123"]
    assert entry["callsign"] == "TEST123"
    assert entry["altitude"] == 18500
    assert entry["velocity"]["speed"] == 255
    assert entry["position"]["lat"] == pytest.approx(33.0001)
    assert entry["position"]["lon"] == pytest.approx(-96.9999)
    assert entry["last_update"] == 1004.0
    assert entry["distance_nm"] == pytest.approx(0.007836068, rel=1e-6)
    assert entry["distance_km"] == pytest.approx(0.014512398, rel=1e-6)


def test_publish_data_without_clients(monkeypatch):
    publisher = adsb_publisher.ADSBPublisher.__new__(adsb_publisher.ADSBPublisher)
    publisher.clients = set()
    publisher.interval = 0
    publisher.src_client = SimpleNamespace(aircraft_data={})

    async def fake_sleep(_):
        raise asyncio.CancelledError

    monkeypatch.setattr(adsb_publisher.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(adsb_publisher.ADSBPublisher.publish_data(publisher))


def test_adsb_publisher_close_cleans_up():
    class DummyWebSocket:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    class DummyThread:
        def __init__(self):
            self.join_called = False

        def is_alive(self):
            return True

        def join(self, timeout=None):
            self.join_called = True

    publisher = adsb_publisher.ADSBPublisher.__new__(adsb_publisher.ADSBPublisher)
    publisher.clients = {DummyWebSocket()}
    publisher._shutdown_event = threading.Event()
    publisher._client_thread = DummyThread()

    asyncio.run(adsb_publisher.ADSBPublisher.close(publisher))

    assert publisher._shutdown_event.is_set()
    ws = next(iter(publisher.clients))
    assert ws.closed
    assert publisher._client_thread.join_called
