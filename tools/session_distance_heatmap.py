#!/usr/bin/env python3
"""Draw assembly-time heat map over geography for first seen points."""

import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple

import matplotlib.pyplot as plt
from matplotlib import colors as mcolors
from matplotlib import ticker as mticker

try:
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit(
        "cartopy is required for geographic plotting. Install with 'pip install cartopy'."
    ) from exc

# DB_PATH = Path("src/database_api/adsb_data.db").resolve()
DB_PATH = Path("tmp/linux_runs/adsb_data.db").resolve()
OUTPUT_PATH = Path("tmp/plots/assembly_geographic_heatmap_linux.png")

# Adjust to clamp the color scale (set to None to auto-scale).
# Example: (0, 150_000) highlights differences up to 150,000 ms (~150 s).
ASSEMBLY_COLOR_RANGE: Optional[Tuple[int, int]] = (0, 150_000)

# Update these coordinates to match the recording device location.
DEVICE_LOCATION = {
    "lat": 32.887342,      # degrees north
    "lon": -97.527519,     # degrees east (negative for west)
    "alt_m": 221.0,   # meters above mean sea level
}

RECEIVER_MARKER_STYLE = {
    "marker": "*",
    "markersize": 14,
    "color": "deepskyblue",
    "markeredgecolor": "black",
    "markeredgewidth": 0.6,
}

def _as_float(value: str):
    if value in ("", None):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def load_session_points(db_path: Path) -> Tuple[List[float], List[float], List[float]]:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    lats: List[float] = []
    lons: List[float] = []
    assembly_ms: List[float] = []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    query = """
        WITH first_path AS (
            SELECT
                session_id,
                lat,
                lon,
                ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY ts ASC) AS rn
            FROM path
            WHERE lat IS NOT NULL AND lon IS NOT NULL
        )
        SELECT
            fs.id AS session_id,
            fp.lat AS first_lat,
            fp.lon AS first_lon,
            a.assembly_time_ms AS assembly_time
        FROM flight_session fs
        JOIN aircraft a ON a.icao = fs.aircraft_icao
        JOIN first_path fp ON fp.session_id = fs.id AND fp.rn = 1
        WHERE a.assembly_time_ms IS NOT NULL
    """
    try:
        for row in conn.execute(query):
            lat = _as_float(row["first_lat"])
            lon = _as_float(row["first_lon"])
            assembly = _as_float(row["assembly_time"])
            if lat is None or lon is None or assembly is None:
                continue
            lats.append(lat)
            lons.append(lon)
            assembly_ms.append(assembly)
    finally:
        conn.close()

    if not lats:
        raise RuntimeError("No usable sessions found in database (missing positions or assembly times).")

    return lats, lons, assembly_ms


def _extent(lons: List[float], lats: List[float], padding_deg: float = 1.0):
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)
    return [min_lon - padding_deg, max_lon + padding_deg, min_lat - padding_deg, max_lat + padding_deg]


def build_geographic_heatmap(lats: List[float], lons: List[float], assembly_ms: List[float], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(10, 8))
    ax = plt.axes(projection=ccrs.PlateCarree())
    ax.set_extent(_extent(lons, lats), crs=ccrs.PlateCarree())
    ax.add_feature(cfeature.LAND.with_scale("50m"), facecolor="#f0f0f0")
    ax.add_feature(cfeature.OCEAN.with_scale("50m"), facecolor="#c6dbef")
    ax.add_feature(cfeature.BORDERS.with_scale("50m"), linestyle=":", linewidth=0.5)
    ax.add_feature(cfeature.STATES.with_scale("50m"), linewidth=0.4)
    ax.add_feature(cfeature.COASTLINE.with_scale("50m"), linewidth=0.6)
    norm = None
    if ASSEMBLY_COLOR_RANGE is not None:
        vmin, vmax = ASSEMBLY_COLOR_RANGE
        norm = mcolors.Normalize(vmin=vmin, vmax=vmax)

    scatter = ax.scatter(
        lons,
        lats,
        c=assembly_ms,
        cmap="inferno",
        norm=norm,
        s=50,
        alpha=0.8,
        transform=ccrs.PlateCarree(),
        edgecolor="black",
        linewidth=0.2,
    )
    if DEVICE_LOCATION.get("lat") is not None and DEVICE_LOCATION.get("lon") is not None:
        ax.plot(
            DEVICE_LOCATION["lon"],
            DEVICE_LOCATION["lat"],
            transform=ccrs.PlateCarree(),
            label="Receiver",
            **RECEIVER_MARKER_STYLE,
        )
        ax.text(
            DEVICE_LOCATION["lon"] + 0.05,
            DEVICE_LOCATION["lat"] + 0.05,
            "Receiver",
            fontsize=9,
            fontweight="bold",
            color=RECEIVER_MARKER_STYLE["color"],
            transform=ccrs.PlateCarree(),
        )
    cbar = fig.colorbar(scatter, ax=ax, orientation="vertical", pad=0.01)
    cbar.set_label("Assembly time (s)")

    def _format_seconds(value, _pos):
        return f"{value / 1000:.0f}"

    cbar.formatter = mticker.FuncFormatter(_format_seconds)
    cbar.update_ticks()
    ax.set_title("Assembly Time at First Recorded Position")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def main() -> None:
    lats, lons, assembly_ms = load_session_points(DB_PATH)
    build_geographic_heatmap(lats, lons, assembly_ms, OUTPUT_PATH)
    print(f"Geographic heat map saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
