"""Flask REST API for presenting ADS-B data from the database."""

from __future__ import annotations

import html
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from flask import Flask, jsonify


app = Flask(__name__)


def _get_db_path() -> Path:
    env_path = os.environ.get("ADSB_DB_PATH")
    if env_path:
        return Path(env_path)
    return Path(__file__).with_name("adsb_data.db")


DB_PATH = _get_db_path()
_SCHEMA_INITIALIZED = False
_LOCAL_TZ = datetime.now().astimezone().tzinfo or timezone.utc
_LOCAL_TZ_NAME = datetime.now(_LOCAL_TZ).tzname() or ""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    global _SCHEMA_INITIALIZED
    if _SCHEMA_INITIALIZED:
        return
    schema_path = Path(__file__).with_name("adsb_db_schema.sql")
    if schema_path.exists():
        try:
            script = schema_path.read_text(encoding="utf-8")
            conn.executescript(script)
        except Exception as exc:
            app.logger.warning("Failed to apply schema from %s: %s", schema_path, exc)
    _SCHEMA_INITIALIZED = True


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _query_all_aircraft() -> List[sqlite3.Row]:
    query = """
    WITH latest_path AS (
        SELECT
            ranked.session_id,
            ranked.icao,
            ranked.ts,
            ranked.ts_iso,
            ranked.lat,
            ranked.lon,
            ranked.alt,
            ranked.velocity,
            ranked.track,
            ranked.vertical_rate,
            ranked.type
        FROM (
            SELECT
                p.*,
                ROW_NUMBER() OVER (PARTITION BY icao ORDER BY ts DESC, id DESC) AS rn
            FROM path p
        ) AS ranked
        WHERE ranked.rn = 1
    )
    SELECT
        a.icao,
        a.callsign,
        a.first_seen,
        a.last_seen,
        lp.lat,
        lp.lon,
        lp.alt,
        lp.velocity,
        lp.track,
        lp.vertical_rate,
        lp.ts AS position_timestamp,
        lp.ts_iso AS position_timestamp_iso,
        lp.type AS velocity_type
    FROM aircraft a
    LEFT JOIN latest_path lp ON lp.icao = a.icao
    ORDER BY a.last_seen DESC
    """
    with _get_connection() as conn:
        return conn.execute(query).fetchall()


def _query_aircraft(icao: str) -> Optional[sqlite3.Row]:
    query = """
    WITH latest_path AS (
        SELECT
            ranked.session_id,
            ranked.icao,
            ranked.ts,
            ranked.ts_iso,
            ranked.lat,
            ranked.lon,
            ranked.alt,
            ranked.velocity,
            ranked.track,
            ranked.vertical_rate,
            ranked.type
        FROM (
            SELECT
                p.*,
                ROW_NUMBER() OVER (PARTITION BY icao ORDER BY ts DESC, id DESC) AS rn
            FROM path p
        ) AS ranked
        WHERE ranked.rn = 1
    )
    SELECT
        a.icao,
        a.callsign,
        a.first_seen,
        a.last_seen,
        lp.lat,
        lp.lon,
        lp.alt,
        lp.velocity,
        lp.track,
        lp.vertical_rate,
        lp.ts AS position_timestamp,
        lp.ts_iso AS position_timestamp_iso,
        lp.type AS velocity_type
    FROM aircraft a
    LEFT JOIN latest_path lp ON lp.icao = a.icao
    WHERE a.icao = ?
    """
    with _get_connection() as conn:
        return conn.execute(query, (icao,)).fetchone()


def _serialize_aircraft(row: sqlite3.Row) -> Dict[str, object]:
    def _fmt_ts(ts: Optional[float]) -> Optional[str]:
        if ts is None:
            return None
        try:
            local_dt = datetime.fromtimestamp(ts, tz=_LOCAL_TZ)
            return local_dt.strftime("%Y-%m-%d %I:%M:%S %p")
        except (ValueError, OSError):
            return None

    position = None
    if row["lat"] is not None or row["lon"] is not None:
        altitude = row["alt"]
        if altitude is not None:
            altitude = int(round(altitude))
        position = {
            "lat": row["lat"],
            "lon": row["lon"],
            "altitude": altitude,
            "timestamp": row["position_timestamp"],
            "timestamp_iso": row["position_timestamp_iso"],
            "timestamp_formatted": _fmt_ts(row["position_timestamp"]),
        }
    velocity = None
    if row["velocity"] is not None or row["track"] is not None or row["vertical_rate"] is not None:
        velocity = {
            "speed": row["velocity"],
            "track": row["track"],
            "vertical_rate": row["vertical_rate"],
            "type": row["velocity_type"],
        }
    callsign = row["callsign"] or ""
    callsign = callsign.replace("_", " ").strip()
    return {
        "icao": row["icao"],
        "callsign": callsign,
        "first_seen_epoch": row["first_seen"],
        "first_seen": _fmt_ts(row["first_seen"]),
        "last_seen_epoch": row["last_seen"],
        "last_seen": _fmt_ts(row["last_seen"]),
        "position": position,
        "velocity": velocity,
    }


def get_aircraft_data() -> List[Dict[str, object]]:
    return [_serialize_aircraft(row) for row in _query_all_aircraft()]


@app.route("/api/aircraft", methods=["GET"])
def api_aircraft():
    """Return all recorded aircraft data."""
    return jsonify(get_aircraft_data())


@app.route("/api/aircraft/<icao>", methods=["GET"])
def api_aircraft_detail(icao: str):
    """Return details for a specific aircraft by ICAO."""
    row = _query_aircraft(icao)
    if row is None:
        return jsonify({"error": "Aircraft not found"}), 404
    return jsonify(_serialize_aircraft(row))


@app.route("/")
def home():
    aircraft = get_aircraft_data()
    cutoff = time.time() - 300
    recent_aircraft = [ac for ac in aircraft if ac.get("last_seen_epoch") and ac["last_seen_epoch"] >= cutoff]

    rows = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        "<meta http-equiv=\"refresh\" content=\"3\" />",
        "<title>ADS-B Aircraft Data</title>",
        "</head>",
        "<body>",
        "<h1>ADS-B Aircraft Data</h1>",
    ]
    if recent_aircraft:
        rows.append('<table border="1" cellpadding="5">')
        tz_suffix = f" ({_LOCAL_TZ_NAME})" if _LOCAL_TZ_NAME else ""
        rows.append(
            f"<tr><th>ICAO</th><th>Callsign</th><th>Latitude</th><th>Longitude</th><th>Altitude (ft)</th><th>Last Seen{tz_suffix}</th></tr>"
        )
        for ac in recent_aircraft:
            position = ac.get("position") or {}
            callsign = ac.get("callsign", "")
            display_callsign = html.escape(callsign) if callsign else "&nbsp;"
            altitude = position.get("altitude")
            altitude_display = str(altitude) if altitude is not None else ""
            rows.append(
                "<tr>"
                f"<td>{ac['icao']}</td>"
                f"<td>{display_callsign}</td>"
                f"<td>{position.get('lat', '')}</td>"
                f"<td>{position.get('lon', '')}</td>"
                f"<td>{altitude_display}</td>"
                f"<td>{ac.get('last_seen', '') or ''}</td>"
                "</tr>"
            )
        rows.append("</table>")
    else:
        rows.append("<p>No aircraft observed in the last 5 minutes.</p>")
    rows.extend(["</body>", "</html>"])
    return "\n".join(rows)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
