"""Flask REST API for presenting ADS-B data from the database."""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from flask import Flask, jsonify, render_template, request, url_for
from jinja2.runtime import Undefined


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

DEFAULT_LIVE_WINDOW_SECONDS = 300
DEFAULT_MAP_CENTER: Tuple[float, float] = (32.7767, -96.7970)
DEFAULT_MAP_ZOOM = 5


def _format_timestamp(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    try:
        local_dt = datetime.fromtimestamp(ts, tz=_LOCAL_TZ)
    except (ValueError, OSError):
        return None
    return local_dt.strftime("%Y-%m-%d %I:%M:%S %p")


def _filter_recent_aircraft(seconds: int = DEFAULT_LIVE_WINDOW_SECONDS) -> List[Dict[str, object]]:
    cutoff = time.time() - seconds
    return [ac for ac in get_aircraft_data() if ac.get("last_seen_epoch") and ac["last_seen_epoch"] >= cutoff]


def _query_path_history(limit: int = 200) -> List[sqlite3.Row]:
    query = """
    SELECT
        p.id,
        p.session_id,
        p.icao,
        p.ts,
        p.ts_iso,
        p.lat,
        p.lon,
        p.alt,
        p.velocity,
        p.track,
        p.vertical_rate,
        a.callsign
    FROM path p
    LEFT JOIN aircraft a ON a.icao = p.icao
    ORDER BY p.ts DESC, p.id DESC
    LIMIT ?
    """
    with _get_connection() as conn:
        return conn.execute(query, (limit,)).fetchall()


def _serialize_path(row: sqlite3.Row) -> Dict[str, object]:
    return {
        "id": row["id"],
        "icao": row["icao"],
        "callsign": (row["callsign"] or "").replace("_", " ").strip(),
        "session_id": row["session_id"],
        "lat": row["lat"],
        "lon": row["lon"],
        "alt": row["alt"],
        "velocity": row["velocity"],
        "track": row["track"],
        "vertical_rate": row["vertical_rate"],
        "timestamp_epoch": row["ts"],
        "timestamp_iso": row["ts_iso"],
        "timestamp": _format_timestamp(row["ts"]),
    }


def _compute_map_center(aircraft: Sequence[Dict[str, object]]) -> Tuple[float, float]:
    coords: List[Tuple[float, float]] = []
    for ac in aircraft:
        position = ac.get("position") or {}
        lat = position.get("lat")
        lon = position.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            coords.append((float(lat), float(lon)))
    if not coords:
        return DEFAULT_MAP_CENTER
    avg_lat = sum(c[0] for c in coords) / len(coords)
    avg_lon = sum(c[1] for c in coords) / len(coords)
    return (avg_lat, avg_lon)


@app.template_filter("format_coord")
def _format_coord_filter(value: object) -> str:
    if isinstance(value, Undefined) or value in (None, ""):
        return ""
    try:
        return f"{float(value):.6f}"
    except (TypeError, ValueError):
        return ""


@app.context_processor
def _inject_template_globals():
    return {"timezone_name": _LOCAL_TZ_NAME}


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
            "timestamp_formatted": _format_timestamp(row["position_timestamp"]),
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
        "first_seen": _format_timestamp(row["first_seen"]),
        "last_seen_epoch": row["last_seen"],
        "last_seen": _format_timestamp(row["last_seen"]),
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


@app.route("/live", methods=["GET"])
def live_data():
    aircraft = _filter_recent_aircraft()
    window_minutes = max(1, DEFAULT_LIVE_WINDOW_SECONDS // 60)
    return render_template(
        "live_data.html",
        title="Live ADS-B Data",
        aircraft=aircraft,
        window_minutes=window_minutes,
    )


@app.route("/historical", methods=["GET"])
def historical_data():
    aircraft = get_aircraft_data()
    return render_template("historical_data.html", title="Historical Records", aircraft=aircraft)


@app.route("/icao", methods=["GET"])
def icao_lookup():
    query = (request.args.get("icao", "") or "").strip().upper()
    result: Optional[Dict[str, object]] = None
    if query:
        row = _query_aircraft(query)
        if row is None:
            result = {"error": f"No aircraft found for ICAO {query}."}
        else:
            result = _serialize_aircraft(row)
    return render_template("icao_lookup.html", title="ICAO Lookup", query=query, result=result)


@app.route("/flight-paths", methods=["GET"])
def flight_paths():
    limit = request.args.get("limit", type=int) or 200
    limit = max(10, min(limit, 1000))
    paths = [_serialize_path(row) for row in _query_path_history(limit)]
    return render_template(
        "flight_paths.html",
        title="Recent Flight Paths",
        paths=paths,
    )


@app.route("/live-map", methods=["GET"])
def live_map():
    aircraft = _filter_recent_aircraft()
    center = _compute_map_center(aircraft)
    return render_template(
        "live_map.html",
        title="Live Aircraft Map",
        aircraft=aircraft,
        refresh_interval=5,
        default_center=center,
        default_zoom=DEFAULT_MAP_ZOOM,
    )


@app.route("/")
def home():
    cards = [
        {
            "title": "Live ADS-B Data",
            "description": "View aircraft detected in the last five minutes with key telemetry.",
            "href": url_for("live_data"),
            "cta": "Open Live View",
        },
        {
            "title": "Historical Records",
            "description": "Browse a catalog of all aircraft ever recorded by WaveTap.",
            "href": url_for("historical_data"),
            "cta": "Review History",
        },
        {
            "title": "ICAO Lookup",
            "description": "Search for a specific aircraft by ICAO identifier.",
            "href": url_for("icao_lookup"),
            "cta": "Lookup ICAO",
        },
        {
            "title": "Flight Paths",
            "description": "Inspect recent track points captured across all aircraft.",
            "href": url_for("flight_paths"),
            "cta": "View Tracks",
        },
        {
            "title": "Live Map",
            "description": "Visualize active aircraft on an interactive global map.",
            "href": url_for("live_map"),
            "cta": "Launch Map",
        },
    ]
    return render_template("home.html", title="WaveTap Control Center", cards=cards)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
