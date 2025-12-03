#!/usr/bin/env python3
"""Test the session timeout functionality."""

import sqlite3

# Add src to path
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from database_api.adsb_db import DBWorker


def test_session_timeout():
    """Test that sessions are closed when there's no activity for 5 minutes."""

    # Create a temporary database
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")

        # Initialize the database worker
        worker = DBWorker(db_path)
        worker.start()

        # Give it time to initialize
        time.sleep(0.5)

        try:
            # Connect to the database to manually insert test data
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            cur = conn.cursor()

            # Create a test session that started 10 minutes ago
            session_id = "test_session_1"
            icao = "ABC123"
            current_time = time.time()
            start_time = current_time - 600  # 10 minutes ago

            # Insert an aircraft
            cur.execute(
                "INSERT INTO aircraft (icao, callsign, first_seen, last_seen) VALUES (?, ?, ?, ?)",
                (icao, "TEST", start_time, current_time)
            )

            # Insert a flight session
            cur.execute(
                "INSERT INTO flight_session (id, aircraft_icao, start_time) VALUES (?, ?, ?)",
                (session_id, icao, start_time)
            )

            # Insert a path record from 6 minutes ago (within timeout)
            cur.execute(
                "INSERT INTO path (session_id, icao, ts, ts_iso, lat, lon, alt) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, icao, current_time - 360, "2025-01-01T00:00:00Z", 40.0, -105.0, 35000.0)
            )

            # Insert another path record from 4 minutes ago (within timeout)
            cur.execute(
                "INSERT INTO path (session_id, icao, ts, ts_iso, lat, lon, alt) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, icao, current_time - 240, "2025-01-01T00:00:00Z", 40.1, -105.1, 35000.0)
            )

            conn.commit()

            # Verify session has no end_time initially
            result = cur.execute("SELECT end_time FROM flight_session WHERE id=?", (session_id,)).fetchone()
            assert result[0] is None, "Session should not have end_time initially"
            print("✓ Session created without end_time")

            # Call timeout check with current time (should NOT timeout yet - last path is only 4 minutes old)
            cur = conn.cursor()
            worker._check_session_timeouts(cur, current_time)
            conn.commit()

            result = cur.execute("SELECT end_time FROM flight_session WHERE id=?", (session_id,)).fetchone()
            assert result[0] is None, "Session should NOT timeout yet (last activity 4 min ago)"
            print("✓ Session NOT closed when inactivity is 4 minutes")

            # Call timeout check with time 6+ minutes in the future
            future_time = current_time + 361  # 1 minute after the 5-minute timeout
            cur = conn.cursor()
            worker._check_session_timeouts(cur, future_time)
            conn.commit()

            result = cur.execute("SELECT end_time FROM flight_session WHERE id=?", (session_id,)).fetchone()
            assert result[0] is not None, "Session should be closed after timeout"
            print(f"✓ Session closed after timeout. End time set to: {result[0]}")

            # Verify end_time is approximately what we passed
            end_time = result[0]
            assert abs(end_time - future_time) < 1, "End time should match the timeout check time"
            print("✓ End time is correct (within 1 second of check time)")

            conn.close()
            print("\n✅ All tests passed!")

        finally:
            worker.stop()
            worker.join(timeout=2)


if __name__ == "__main__":
    test_session_timeout()
