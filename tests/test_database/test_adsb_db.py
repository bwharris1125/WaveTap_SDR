import os
import sqlite3
import time
import uuid
from pathlib import Path

from database_api import adsb_module
from database_api.adsb_db import AircraftState, DBWorker


def test_aircraftstate_defaults():
    a = AircraftState(icao="ABCDEF")
    assert a.icao == "ABCDEF"
    assert a.callsign is None
    assert a.session_id is None
    assert isinstance(a.last_seen, float)
    # last_seen should be recent (within last 5 seconds)
    assert time.time() - a.last_seen < 5


def test_dbworker_processes_tasks(tmp_path):
    # place temporary sqlite file inside the project src/database_api folder so it
    # lives alongside other DB artifacts during test runs
    db_folder = Path(__file__).resolve().parents[2] / "src" / "database_api"
    db_folder.mkdir(parents=True, exist_ok=True)
    db_file = db_folder / f"test_adsb_{int(time.time() * 1000)}.db"
    db_path = str(db_file)

    worker = DBWorker(db_path=db_path)
    worker.start()

    try:
        # enqueue an upsert for an aircraft
        icao = "ABC123"
        callsign = "TEST123"
        ts = time.time()
        worker.enqueue(("upsert_aircraft", icao, callsign, ts, ts))

        # create a session and add a path point
        session_id = str(uuid.uuid4())
        worker.enqueue(("start_session", session_id, icao, ts))
        iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
        worker.enqueue(("insert_path", session_id, icao, ts, iso, 32.0, -96.0, 1000.0, None, None, None, None))
        worker.enqueue(("end_session", session_id, ts + 10.0))

        # wait for DB to be populated (timeout after ~5s)
        deadline = time.time() + 5.0
        rows_found = False
        while time.time() < deadline:
            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                cur = conn.cursor()
                try:
                    cur.execute("SELECT count(*) FROM path")
                    cnt = cur.fetchone()[0]
                    if cnt >= 1:
                        rows_found = True
                        break
                except sqlite3.OperationalError:
                    # table may not be initialized yet
                    pass
                finally:
                    conn.close()
            time.sleep(0.1)

        assert rows_found, "DBWorker did not insert path row in time"

        # verify aircraft row exists
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT icao, callsign FROM aircraft WHERE icao = ?", (icao,))
        row = cur.fetchone()
        conn.close()
        assert row is not None
        assert row[0] == icao
        assert row[1] == callsign

    finally:
        # stop worker and join
        worker.stop()
        worker.join(timeout=3.0)
        # cleanup file and WAL/SHM artifacts
        try:
            if os.path.exists(db_path):
                os.remove(db_path)
            for suffix in ("-wal", "-shm"):
                p = db_path + suffix
                if os.path.exists(p):
                    os.remove(p)
        except Exception:
            pass


def test_dbworker_handle_branches(monkeypatch):
    # Force fallback schema by pretending schema file is absent
    monkeypatch.setattr(Path, "exists", lambda self: False)

    worker = DBWorker.__new__(DBWorker)
    worker.db_path = ":memory:"
    worker.q = None
    worker.conn = sqlite3.connect(":memory:")

    worker._init_schema()
    cur = worker.conn.cursor()

    worker._handle(("upsert_aircraft", "ICAO1", "CALL", 1.0, 2.0), cur)
    worker.conn.commit()

    worker._handle(("start_session", "sess", "ICAO1", 3.0), cur)
    worker._handle(("end_session", "sess", 4.0), cur)
    worker._handle((
        "insert_path",
        "sess",
        "ICAO1",
        5.0,
        "2024-01-01T00:00:05Z",
        32.0,
        -96.0,
        1000.0,
        250.0,
        90.0,
        0.0,
        "airborne",
    ), cur)

    worker.conn.commit()

    cur.execute("SELECT icao, callsign FROM aircraft")
    row = cur.fetchone()
    assert row == ("ICAO1", "CALL")

    cur.execute("SELECT end_time FROM flight_session WHERE id=?", ("sess",))
    sess_row = cur.fetchone()
    assert sess_row[0] == 4.0

    cur.execute("SELECT COUNT(*) FROM path")
    assert cur.fetchone()[0] == 1

    # Unknown task should not raise
    worker._handle(("bogus",), cur)

    worker.conn.close()


def test_dbworker_upgrades_legacy_path_table(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS aircraft (
            icao TEXT PRIMARY KEY,
            callsign TEXT,
            first_seen REAL,
            last_seen REAL
        );
        CREATE TABLE IF NOT EXISTS path (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            icao TEXT,
            ts REAL,
            ts_iso TEXT,
            lat REAL,
            lon REAL,
            alt REAL
        );
        """
    )
    conn.commit()
    conn.close()

    worker = DBWorker.__new__(DBWorker)
    worker.db_path = str(db_path)
    worker.q = None
    worker.conn = sqlite3.connect(worker.db_path)
    worker._stop_event = None
    worker._poll_rate = 0.5

    worker._init_schema()

    cur = worker.conn.execute("PRAGMA table_info(path)")
    columns = {row[1] for row in cur.fetchall()}
    worker.conn.close()

    assert {"velocity", "track", "vertical_rate", "type"}.issubset(columns)


def test_adsb_module_schema_upgrade(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy_module.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS aircraft (
            icao TEXT PRIMARY KEY,
            callsign TEXT,
            first_seen REAL,
            last_seen REAL
        );
        CREATE TABLE IF NOT EXISTS path (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            icao TEXT,
            ts REAL,
            ts_iso TEXT,
            lat REAL,
            lon REAL,
            alt REAL
        );
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("ADSB_DB_PATH", str(db_path))
    monkeypatch.setattr(adsb_module, "_SCHEMA_INITIALIZED", {})

    with adsb_module._get_connection() as conn:
        conn.execute("SELECT 1")

    conn = sqlite3.connect(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(path)").fetchall()}
    conn.close()

    assert {"velocity", "track", "vertical_rate", "type"}.issubset(columns)