#!/usr/bin/env python3
"""Export ADS-B session summary data to CSV."""

import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

# DB_PATH = Path("src/database_api/adsb_data.db").resolve()
# OUTPUT_PATH = Path("tmp/csv_exports/session_paths.csv")
DB_PATH = Path("tmp/linux_runs/adsb_data.db").resolve()
OUTPUT_PATH = Path("tmp/csv_exports/linux_session_paths.csv")

PATH_COLUMNS = (
    "ts",
    "ts_iso",
    "lat",
    "lon",
    "alt",
    "velocity",
    "track",
    "vertical_rate",
    "type",
)

CSV_COLUMNS = [
    "icao",
    "callsign",
    "assembly_time_ms",
    "session_id",
    "session_start",
    "session_start_iso",
    "session_end",
    "session_end_iso",
    "first_ts",
    "first_ts_iso",
    "first_lat",
    "first_lon",
    "first_alt",
    "first_velocity",
    "first_track",
    "first_vertical_rate",
    "first_type",
    "last_ts",
    "last_ts_iso",
    "last_lat",
    "last_lon",
    "last_alt",
    "last_velocity",
    "last_track",
    "last_vertical_rate",
    "last_type",
]


def _iso(ts: Optional[float]) -> str:
    if ts is None:
        return ""
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (OSError, OverflowError):
        return ""


def _fetch_path_edge(
    conn: sqlite3.Connection,
    session_id: str,
    order: str,
) -> Dict[str, Optional[float]]:
    cur = conn.execute(
        f"SELECT {', '.join(PATH_COLUMNS)} FROM path WHERE session_id=? ORDER BY ts {order} LIMIT 1",
        (session_id,),
    )
    row = cur.fetchone()
    if row is None:
        return {column: None for column in PATH_COLUMNS}
    if isinstance(row, sqlite3.Row):
        return {column: row[column] for column in PATH_COLUMNS}
    return {column: row[idx] for idx, column in enumerate(PATH_COLUMNS)}


def export_sessions(db_path: Path, output_path: Path) -> None:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """
            SELECT fs.id AS session_id,
                   fs.aircraft_icao AS icao,
                   fs.start_time,
                   fs.end_time,
                   a.callsign,
                   a.assembly_time_ms
            FROM flight_session fs
            JOIN aircraft a ON a.icao = fs.aircraft_icao
            ORDER BY fs.aircraft_icao, fs.start_time
            """
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=CSV_COLUMNS)
            writer.writeheader()

            for session in cur:
                first_path = _fetch_path_edge(conn, session["session_id"], "ASC")
                last_path = _fetch_path_edge(conn, session["session_id"], "DESC")

                row = {
                    "icao": session["icao"],
                    "callsign": session["callsign"],
                    "assembly_time_ms": session["assembly_time_ms"],
                    "session_id": session["session_id"],
                    "session_start": session["start_time"],
                    "session_start_iso": _iso(session["start_time"]),
                    "session_end": session["end_time"],
                    "session_end_iso": _iso(session["end_time"]),
                    "first_ts": first_path["ts"],
                    "first_ts_iso": first_path.get("ts_iso") or _iso(first_path["ts"]),
                    "first_lat": first_path["lat"],
                    "first_lon": first_path["lon"],
                    "first_alt": first_path["alt"],
                    "first_velocity": first_path["velocity"],
                    "first_track": first_path["track"],
                    "first_vertical_rate": first_path["vertical_rate"],
                    "first_type": first_path["type"],
                    "last_ts": last_path["ts"],
                    "last_ts_iso": last_path.get("ts_iso") or _iso(last_path["ts"]),
                    "last_lat": last_path["lat"],
                    "last_lon": last_path["lon"],
                    "last_alt": last_path["alt"],
                    "last_velocity": last_path["velocity"],
                    "last_track": last_path["track"],
                    "last_vertical_rate": last_path["vertical_rate"],
                    "last_type": last_path["type"],
                }

                writer.writerow(row)
    finally:
        conn.close()


def main() -> None:
    export_sessions(DB_PATH, OUTPUT_PATH)
    print(f"Export complete: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
