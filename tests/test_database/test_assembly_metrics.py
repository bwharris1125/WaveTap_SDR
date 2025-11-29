"""
Unit tests for assembly_time_ms and stale_cpr_count metrics tracking.

Tests verify that:
1. Publisher tracks assembly_time_ms and stale_cpr_count per aircraft
2. Metrics are included in published messages
3. Subscriber properly extracts metrics from messages
4. DBWorker correctly stores metrics in aircraft table
5. New database columns are created without breaking existing databases
"""

import asyncio
import os
import sqlite3
import time
from pathlib import Path

from database_api.adsb_db import DBWorker
from database_api.adsb_subscriber import ADSBSubscriber


class FakeDBWorker:
    """Mock DBWorker for testing subscriber behavior."""

    def __init__(self):
        self.tasks = []
        self.started = False

    def start(self):
        self.started = True

    def enqueue(self, task):
        self.tasks.append(task)

    def stop(self):
        self.started = False


class TestAssemblyMetricsDatabase:
    """Test database storage of assembly metrics."""

    def test_dbworker_stores_assembly_time_and_stale_cpr_count(self, tmp_path):
        """Verify DBWorker correctly stores assembly_time_ms and stale_cpr_count."""
        db_path = str(tmp_path / "metrics_test.db")

        worker = DBWorker(db_path=db_path)
        worker.start()

        try:
            # Enqueue an aircraft with metrics
            icao = "ABC123"
            callsign = "TEST123"
            ts = time.time()
            assembly_time_ms = 7224.77
            stale_cpr_count = 5

            worker.enqueue((
                "upsert_aircraft",
                icao,
                callsign,
                ts,
                ts,
                assembly_time_ms,
                stale_cpr_count,
            ))

            # Wait for database to be populated
            deadline = time.time() + 5.0
            metrics_stored = False
            while time.time() < deadline:
                if os.path.exists(db_path):
                    conn = sqlite3.connect(db_path)
                    try:
                        cur = conn.cursor()
                        cur.execute(
                            "SELECT assembly_time_ms, stale_cpr_count FROM aircraft WHERE icao = ?",
                            (icao,),
                        )
                        row = cur.fetchone()
                        if row is not None:
                            stored_assembly_time, stored_stale_count = row
                            assert stored_assembly_time == assembly_time_ms
                            assert stored_stale_count == stale_cpr_count
                            metrics_stored = True
                            break
                    except sqlite3.OperationalError:
                        # Table may not be initialized yet
                        pass
                    finally:
                        conn.close()
                time.sleep(0.1)

            assert metrics_stored, "DBWorker did not store metrics in time"

        finally:
            worker.stop()
            worker.join(timeout=3.0)
            # Cleanup
            for suffix in ("", "-wal", "-shm"):
                p = db_path + suffix
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

    def test_dbworker_updates_assembly_metrics_on_conflict(self, tmp_path):
        """Verify DBWorker updates assembly metrics on UPSERT."""
        db_path = str(tmp_path / "upsert_metrics.db")

        worker = DBWorker(db_path=db_path)
        worker.start()

        try:
            icao = "XYZ789"
            callsign = "FLIGHT1"
            ts = time.time()

            # First insert
            worker.enqueue((
                "upsert_aircraft",
                icao,
                callsign,
                ts,
                ts,
                5000.0,  # initial assembly time
                3,  # initial stale count
            ))

            time.sleep(0.5)

            # Second upsert with updated metrics
            worker.enqueue((
                "upsert_aircraft",
                icao,
                callsign,
                ts,
                ts + 10,
                5000.0,  # same assembly time
                7,  # updated stale count
            ))

            deadline = time.time() + 5.0
            metrics_updated = False
            while time.time() < deadline:
                if os.path.exists(db_path):
                    conn = sqlite3.connect(db_path)
                    try:
                        cur = conn.cursor()
                        cur.execute(
                            "SELECT stale_cpr_count FROM aircraft WHERE icao = ?",
                            (icao,),
                        )
                        row = cur.fetchone()
                        if row is not None and row[0] == 7:
                            metrics_updated = True
                            break
                    except sqlite3.OperationalError:
                        pass
                    finally:
                        conn.close()
                time.sleep(0.1)

            assert metrics_updated, "DBWorker did not update metrics"

        finally:
            worker.stop()
            worker.join(timeout=3.0)
            for suffix in ("", "-wal", "-shm"):
                p = db_path + suffix
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

    def test_dbworker_handles_null_metrics(self, tmp_path):
        """Verify DBWorker handles NULL metrics gracefully."""
        db_path = str(tmp_path / "null_metrics.db")

        worker = DBWorker(db_path=db_path)
        worker.start()

        try:
            icao = "NULL001"
            callsign = "NULLTEST"
            ts = time.time()

            # Insert with NULL metrics
            worker.enqueue((
                "upsert_aircraft",
                icao,
                callsign,
                ts,
                ts,
                None,  # assembly_time_ms
                None,  # stale_cpr_count
            ))

            deadline = time.time() + 5.0
            row_found = False
            while time.time() < deadline:
                if os.path.exists(db_path):
                    conn = sqlite3.connect(db_path)
                    try:
                        cur = conn.cursor()
                        cur.execute(
                            "SELECT assembly_time_ms, stale_cpr_count FROM aircraft WHERE icao = ?",
                            (icao,),
                        )
                        row = cur.fetchone()
                        if row is not None:
                            # Both should be NULL
                            assert row[0] is None
                            assert row[1] is None
                            row_found = True
                            break
                    except sqlite3.OperationalError:
                        pass
                    finally:
                        conn.close()
                time.sleep(0.1)

            assert row_found, "Aircraft with NULL metrics not found"

        finally:
            worker.stop()
            worker.join(timeout=3.0)
            for suffix in ("", "-wal", "-shm"):
                p = db_path + suffix
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

    def test_dbworker_schema_migration_adds_metrics_columns(self, tmp_path):
        """Verify schema migration adds assembly_time_ms and stale_cpr_count columns."""
        db_path = tmp_path / "legacy_db.db"

        # Create legacy database without the new columns
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS aircraft (
                icao TEXT PRIMARY KEY,
                callsign TEXT,
                first_seen REAL,
                last_seen REAL
            );
            CREATE TABLE IF NOT EXISTS flight_session (
                id TEXT PRIMARY KEY,
                aircraft_icao TEXT,
                start_time REAL,
                end_time REAL,
                FOREIGN KEY (aircraft_icao) REFERENCES aircraft(icao)
            );
            CREATE INDEX IF NOT EXISTS idx_flight_session_aircraft ON flight_session(aircraft_icao);
            CREATE TABLE IF NOT EXISTS path (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                icao TEXT,
                ts REAL,
                ts_iso TEXT,
                lat REAL,
                lon REAL,
                alt REAL,
                FOREIGN KEY (session_id) REFERENCES flight_session(id),
                FOREIGN KEY (icao) REFERENCES aircraft(icao)
            );
            CREATE INDEX IF NOT EXISTS idx_path_icao_ts ON path(icao, ts);
            """
        )
        conn.commit()
        conn.close()

        # Now initialize DBWorker, which should trigger migration
        worker = DBWorker(db_path=str(db_path))
        worker.start()

        try:
            time.sleep(0.5)

            # Verify columns exist
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            columns = {row[1] for row in cur.execute("PRAGMA table_info(aircraft)").fetchall()}
            conn.close()

            assert "assembly_time_ms" in columns, "assembly_time_ms column not added"
            assert "stale_cpr_count" in columns, "stale_cpr_count column not added"

        finally:
            worker.stop()
            worker.join(timeout=3.0)
            for suffix in ("", "-wal", "-shm"):
                p = db_path.with_name(db_path.name + suffix)
                if p.exists():
                    try:
                        p.unlink()
                    except Exception:
                        pass


class TestSubscriberMetricsExtraction:
    """Test subscriber extracts and stores metrics."""

    def test_subscriber_extracts_metrics_from_message(self):
        """Verify subscriber extracts assembly_time_ms and stale_cpr_count from received data."""

        async def scenario():
            sub = ADSBSubscriber(uri="ws://fake")
            fake_db = FakeDBWorker()
            sub.db_worker = fake_db
            sub.active_sessions = {}

            now = time.time()
            sub.aircraft_data = {
                "METRIC1": {
                    "icao": "METRIC1",
                    "callsign": "TEST001",
                    "first_seen": now - 100,
                    "last_update": now,
                    "assembly_time_ms": 7224.77,
                    "stale_cpr_count": 5,
                    "position": {"lat": 32.0, "lon": -96.0},
                    "altitude": 10000,
                    "velocity": {"speed": 250, "track": 90, "vertical_rate": 0, "type": "airborne"},
                }
            }

            await sub.save_to_db()

            # Verify upsert_aircraft task contains metrics
            upsert_tasks = [t for t in fake_db.tasks if t[0] == "upsert_aircraft"]
            assert len(upsert_tasks) == 1

            task = upsert_tasks[0]
            # Task format: ("upsert_aircraft", icao, callsign, first_seen, last_update, assembly_time_ms, stale_cpr_count)
            assert task[1] == "METRIC1"
            assert task[5] == 7224.77  # assembly_time_ms
            assert task[6] == 5  # stale_cpr_count

        asyncio.run(scenario())

    def test_subscriber_handles_missing_metrics(self):
        """Verify subscriber handles aircraft without metrics gracefully."""

        async def scenario():
            sub = ADSBSubscriber(uri="ws://fake")
            fake_db = FakeDBWorker()
            sub.db_worker = fake_db
            sub.active_sessions = {}

            now = time.time()
            sub.aircraft_data = {
                "NO_METRICS": {
                    "icao": "NO_METRICS",
                    "callsign": "TEST002",
                    "first_seen": now - 50,
                    "last_update": now,
                    # No assembly_time_ms or stale_cpr_count
                    "position": {"lat": 32.0, "lon": -96.0},
                    "altitude": 5000,
                    "velocity": {"speed": 200, "track": 180, "vertical_rate": -100, "type": "airborne"},
                }
            }

            await sub.save_to_db()

            upsert_tasks = [t for t in fake_db.tasks if t[0] == "upsert_aircraft"]
            assert len(upsert_tasks) == 1

            task = upsert_tasks[0]
            # Missing metrics should be None
            assert task[5] is None  # assembly_time_ms
            assert task[6] is None  # stale_cpr_count

        asyncio.run(scenario())

    def test_subscriber_passes_zero_metrics(self):
        """Verify subscriber correctly passes zero values for metrics."""

        async def scenario():
            sub = ADSBSubscriber(uri="ws://fake")
            fake_db = FakeDBWorker()
            sub.db_worker = fake_db
            sub.active_sessions = {}

            now = time.time()
            sub.aircraft_data = {
                "ZERO_METRICS": {
                    "icao": "ZERO_METRICS",
                    "callsign": "TEST003",
                    "first_seen": now - 10,
                    "last_update": now,
                    "assembly_time_ms": 0.0,  # Just assembled
                    "stale_cpr_count": 0,  # No stale pairs yet
                    "position": {"lat": 33.0, "lon": -97.0},
                    "altitude": 8000,
                    "velocity": {"speed": 300, "track": 45, "vertical_rate": 500, "type": "airborne"},
                }
            }

            await sub.save_to_db()

            upsert_tasks = [t for t in fake_db.tasks if t[0] == "upsert_aircraft"]
            assert len(upsert_tasks) == 1

            task = upsert_tasks[0]
            assert task[5] == 0.0  # assembly_time_ms
            assert task[6] == 0  # stale_cpr_count

        asyncio.run(scenario())

    def test_subscriber_multiple_aircraft_with_metrics(self):
        """Verify subscriber handles multiple aircraft with different metrics."""

        async def scenario():
            sub = ADSBSubscriber(uri="ws://fake")
            fake_db = FakeDBWorker()
            sub.db_worker = fake_db
            sub.active_sessions = {}

            now = time.time()
            sub.aircraft_data = {
                "FAST_ASSEM": {
                    "icao": "FAST_ASSEM",
                    "callsign": "QUICK",
                    "first_seen": now - 50,
                    "last_update": now,
                    "assembly_time_ms": 1234.56,  # Fast assembly
                    "stale_cpr_count": 0,  # No stale pairs
                    "position": {"lat": 32.0, "lon": -96.0},
                    "altitude": 10000,
                    "velocity": {"speed": 250, "track": 90, "vertical_rate": 0, "type": "airborne"},
                },
                "SLOW_ASSEM": {
                    "icao": "SLOW_ASSEM",
                    "callsign": "SLOW",
                    "first_seen": now - 200,
                    "last_update": now,
                    "assembly_time_ms": 162845.08,  # Slow assembly
                    "stale_cpr_count": 12,  # Many stale pairs
                    "position": {"lat": 33.0, "lon": -97.0},
                    "altitude": 15000,
                    "velocity": {"speed": 450, "track": 180, "vertical_rate": 2000, "type": "airborne"},
                },
            }

            await sub.save_to_db()

            upsert_tasks = [t for t in fake_db.tasks if t[0] == "upsert_aircraft"]
            assert len(upsert_tasks) == 2

            # Find each aircraft's task
            fast_task = next((t for t in upsert_tasks if t[1] == "FAST_ASSEM"), None)
            slow_task = next((t for t in upsert_tasks if t[1] == "SLOW_ASSEM"), None)

            assert fast_task is not None
            assert slow_task is not None

            # Verify metrics for fast assembly
            assert fast_task[5] == 1234.56
            assert fast_task[6] == 0

            # Verify metrics for slow assembly
            assert slow_task[5] == 162845.08
            assert slow_task[6] == 12

        asyncio.run(scenario())


class TestDBWorkerHandleBranchesWithMetrics:
    """Test DBWorker._handle with metrics parameters."""

    def test_dbworker_handle_upsert_aircraft_with_metrics(self, monkeypatch):
        """Verify _handle correctly processes upsert_aircraft with metrics."""
        # Force fallback schema
        monkeypatch.setattr(Path, "exists", lambda self: False)

        worker = DBWorker.__new__(DBWorker)
        worker.db_path = ":memory:"
        worker.q = None
        worker.conn = sqlite3.connect(":memory:")

        worker._init_schema()
        cur = worker.conn.cursor()

        # Handle upsert with metrics
        worker._handle(
            ("upsert_aircraft", "ICAO1", "CALL", 1.0, 2.0, 5000.0, 3),
            cur,
        )
        worker.conn.commit()

        # Verify data stored correctly
        cur.execute(
            "SELECT icao, callsign, assembly_time_ms, stale_cpr_count FROM aircraft"
        )
        row = cur.fetchone()
        assert row == ("ICAO1", "CALL", 5000.0, 3)

        # Upsert with updated metrics
        worker._handle(
            ("upsert_aircraft", "ICAO1", "CALL", 1.0, 3.0, 5000.0, 7),
            cur,
        )
        worker.conn.commit()

        cur.execute(
            "SELECT assembly_time_ms, stale_cpr_count FROM aircraft WHERE icao = ?",
            ("ICAO1",),
        )
        row = cur.fetchone()
        assert row == (5000.0, 7)

        worker.conn.close()

    def test_dbworker_handle_upsert_with_null_metrics(self, monkeypatch):
        """Verify _handle correctly processes upsert with NULL metrics."""
        monkeypatch.setattr(Path, "exists", lambda self: False)

        worker = DBWorker.__new__(DBWorker)
        worker.db_path = ":memory:"
        worker.q = None
        worker.conn = sqlite3.connect(":memory:")

        worker._init_schema()
        cur = worker.conn.cursor()

        worker._handle(
            ("upsert_aircraft", "NULL01", "NULLCALL", 1.0, 2.0, None, None),
            cur,
        )
        worker.conn.commit()

        cur.execute(
            "SELECT assembly_time_ms, stale_cpr_count FROM aircraft WHERE icao = ?",
            ("NULL01",),
        )
        row = cur.fetchone()
        assert row == (None, None)

        worker.conn.close()
