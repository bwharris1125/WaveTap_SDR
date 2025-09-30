import argparse
import asyncio
import io
import json
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from database_api import adsb_subscriber
from database_api.adsb_subscriber import ADSBSubscriber, print_aircraft_data


class FakeDBWorker:
    def __init__(self):
        self.tasks = []
        self.started = False
    def start(self):
        self.started = True
    def enqueue(self, task):
        self.tasks.append(task)
    def stop(self):
        self.started = False

def test_subscriber_periodic_db_write(monkeypatch):
    async def scenario():
        # Setup
        sub = ADSBSubscriber(uri="ws://fake")
        fake_db = FakeDBWorker()
        sub.db_worker = fake_db
        sub.active_sessions = {}

        # Patch setup_db to use fake DBWorker
        monkeypatch.setattr(sub, "setup_db", lambda db_path=None: None)

        # Simulate aircraft data
        now = time.time()
        sub.aircraft_data = {
            "ABC123": {
                "callsign": "TEST123",
                "first_seen": now - 100,
                "last_update": now,
                "position": {"lat": 32.0, "lon": -96.0},
                "altitude": 1000.0,
                "velocity": {"speed": 250, "track": 90, "vertical_rate": 0, "type": "airborne"}
            }
        }

        # Initial save
        await sub.save_to_db()
        await asyncio.sleep(0.1)

        # No duplicate inserts when data unchanged
        await sub.save_to_db()

        # Simulate new data to trigger another insert
        updated_time = now + 1
        sub.aircraft_data["ABC123"]["last_update"] = updated_time
        sub.aircraft_data["ABC123"]["position"]["lat"] = 33.0
        await sub.save_to_db()

        # Check that tasks were enqueued
        assert fake_db.tasks, "No DB tasks enqueued by subscriber"
        upsert_tasks = [t for t in fake_db.tasks if t[0] == "upsert_aircraft"]
        path_tasks = [t for t in fake_db.tasks if t[0] == "insert_path"]
        assert upsert_tasks, "No upsert_aircraft tasks enqueued"
        assert path_tasks, "No insert_path tasks enqueued"
        session_ids = {t[1] for t in path_tasks}
        # Should have one path insert per unique timestamp
        assert len(path_tasks) == 2
        # Upserts happen per save invocation
        assert len(upsert_tasks) == 3

        # Check session tracking
        start_sessions = [t for t in fake_db.tasks if t[0] == "start_session"]
        end_sessions = [t for t in fake_db.tasks if t[0] == "end_session"]
        assert start_sessions, "No session tracking tasks enqueued"
        assert not end_sessions, "Sessions should remain open while data is fresh"
        start_session_ids = {t[1] for t in start_sessions}
        assert len(start_session_ids) == 1
        assert session_ids == start_session_ids

        # Check that session_id is consistent between writes
        assert len(session_ids) == 1, "Session ID should be consistent for same aircraft"

    asyncio.run(scenario())


def test_setup_db_prefers_env_path(monkeypatch, tmp_path):
    captured = {}

    class StubWorker:
        def __init__(self, db_path):
            captured["path"] = db_path
            self.started = False

        def start(self):
            self.started = True

    monkeypatch.setenv("ADSB_DB_PATH", str(tmp_path / "env_path.db"))
    monkeypatch.setattr(adsb_subscriber, "DBWorker", StubWorker)

    sub = ADSBSubscriber("ws://env-test")
    sub.setup_db()

    assert captured["path"].endswith("env_path.db")
    assert sub.db_worker.started
    assert sub.active_sessions == {}
    assert sub.last_saved_ts == {}


def test_save_to_db_requires_worker(caplog):
    caplog.set_level(logging.WARNING)
    sub = ADSBSubscriber("ws://nowhere")
    asyncio.run(sub.save_to_db())
    assert "DB worker not initialized" in caplog.text


def test_save_to_db_handles_missing_position(monkeypatch):
    async def scenario():
        sub = ADSBSubscriber("ws://missing")
        worker = FakeDBWorker()
        sub.db_worker = worker
        sub.active_sessions = {}
        now = time.time()
        sub.aircraft_data = {
            "NO_POS": {
                "callsign": None,
                "first_seen": now - 5,
                "last_update": None,
            },
            "HAS_POS": {
                "callsign": "HAVE",
                "first_seen": now - 10,
                "last_update": now,
                "position": {},
            },
        }

        await sub.save_to_db()

        upsert_tasks = [t for t in worker.tasks if t[0] == "upsert_aircraft"]
        start_sessions = [t for t in worker.tasks if t[0] == "start_session"]
        path_tasks = [t for t in worker.tasks if t[0] == "insert_path"]

        assert len(upsert_tasks) == 2
        assert len(start_sessions) == 1
        assert not path_tasks

    asyncio.run(scenario())


def test_connect_and_listen_processes_messages(monkeypatch):
    class DummyWS:
        def __init__(self, messages):
            self._messages = iter(messages)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def recv(self):
            try:
                return next(self._messages)
            except StopIteration:
                raise asyncio.CancelledError

    messages = [
        json.dumps({"ABC123": {"callsign": "TEST"}}),
        json.dumps(["unexpected"]),
        "not-json",
    ]

    monkeypatch.setattr(adsb_subscriber.websockets, "connect", lambda uri: DummyWS(messages))

    async def scenario():
        sub = ADSBSubscriber("ws://fake")
        with pytest.raises(asyncio.CancelledError):
            await sub.connect_and_listen()
        assert "ABC123" in sub.aircraft_data

    asyncio.run(scenario())


def test_print_aircraft_data_outputs(monkeypatch):
    collector = SimpleNamespace(
        aircraft_data={
            "ABC123": {
                "callsign": "TEST",
                "position": {"lat": 32.5, "lon": -96.7},
                "altitude": 1234,
            }
        }
    )

    buffer = io.StringIO()
    monkeypatch.setattr(adsb_subscriber.sys, "stdout", buffer)

    def fake_sleep(_):
        raise RuntimeError

    monkeypatch.setattr(adsb_subscriber.time, "sleep", fake_sleep)

    with pytest.raises(RuntimeError):
        print_aircraft_data(collector, interval=0)

    output = buffer.getvalue()
    assert "ABC123" in output
    assert "CALLSIGN" in output


def test_adsb_subscriber_main(monkeypatch):
    events = {}

    class DummySubscriber:
        def __init__(self, uri):
            events["uri"] = uri

        def setup_db(self, db_path):
            events["db_path"] = db_path

        async def save_to_db(self):
            events["save_calls"] = events.get("save_calls", 0) + 1

        async def connect_and_listen(self):
            events["connected"] = True

    class DummyParser:
        def __init__(self, *args, **kwargs):
            self.defaults = {}

        def add_argument(self, name, *args, **kwargs):
            if name == "--db":
                self.defaults["db"] = kwargs.get("default")
            elif name == "--uri":
                self.defaults["uri"] = kwargs.get("default")
            return None

        def parse_args(self):
            return SimpleNamespace(
                uri="ws://dummy",
                db=self.defaults.get("db"),
            )

    async def fake_sleep(_):
        raise asyncio.CancelledError

    monkeypatch.delenv("ADSB_DB_PATH", raising=False)
    monkeypatch.setattr(adsb_subscriber, "ADSBSubscriber", DummySubscriber)
    monkeypatch.setattr(argparse, "ArgumentParser", DummyParser)
    monkeypatch.setattr(adsb_subscriber.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(adsb_subscriber.main())

    expected_default = str(Path(adsb_subscriber.__file__).with_name("adsb_data.db"))
    assert events["uri"] == "ws://dummy"
    assert events["db_path"] == expected_default
    assert events["save_calls"] == 1
    assert events["connected"]
