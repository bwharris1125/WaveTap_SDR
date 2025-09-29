import asyncio
import time

import pytest

from src.database.adsb_subscriber import ADSBSubscriber


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

@pytest.mark.asyncio
async def test_subscriber_periodic_db_write(monkeypatch):
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

    # Run save_to_db twice, simulating periodic writes
    await sub.save_to_db()
    await asyncio.sleep(0.1)
    await sub.save_to_db()

    # Check that tasks were enqueued
    assert fake_db.tasks, "No DB tasks enqueued by subscriber"
    upsert_tasks = [t for t in fake_db.tasks if t[0] == "upsert_aircraft"]
    path_tasks = [t for t in fake_db.tasks if t[0] == "insert_path"]
    assert upsert_tasks, "No upsert_aircraft tasks enqueued"
    assert path_tasks, "No insert_path tasks enqueued"
    # Should have at least two upserts and two path inserts (from two calls)
    assert len(upsert_tasks) >= 2
    assert len(path_tasks) >= 2

    # Check session tracking
    session_tasks = [t for t in fake_db.tasks if t[0] in ("start_session", "end_session")]
    assert session_tasks, "No session tracking tasks enqueued"

    # Check that session_id is consistent between writes
    session_ids = set(t[1] for t in path_tasks)
    assert len(session_ids) == 1, "Session ID should be consistent for same aircraft"
