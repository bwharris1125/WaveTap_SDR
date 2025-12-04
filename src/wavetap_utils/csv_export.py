"""
CSV Export Module for ADS-B Aircraft Data

This module provides utilities to export aircraft tracking data from the SQLite
database to CSV format. Supports exporting aircraft data, flight sessions, and
complete flight paths with flexible filtering options.
**Code partially generated with Gitlab Copilot.**
"""

import argparse
import csv
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CSVExporter:
    """Export aircraft data from SQLite database to CSV files."""

    def __init__(self, db_path: str):
        """
        Initialize CSV exporter.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        """
        Create and return a database connection.

        Returns:
            sqlite3.Connection: Database connection with row factory.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def export_aircraft(
        self,
        output_path: str,
        filters: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Export all aircraft records to CSV.

        Args:
            output_path: Path where CSV file will be written.
            filters: Optional dictionary with filter criteria:
                - 'callsign': Filter by callsign (substring match)
                - 'min_first_seen': Filter by minimum first_seen timestamp
                - 'max_last_seen': Filter by maximum last_seen timestamp

        Returns:
            Number of records exported.
        """
        conn = self._get_connection()
        try:
            query = "SELECT * FROM aircraft WHERE 1=1"
            params = []

            if filters:
                if "callsign" in filters:
                    query += " AND callsign LIKE ?"
                    params.append(f"%{filters['callsign']}%")
                if "min_first_seen" in filters:
                    query += " AND first_seen >= ?"
                    params.append(filters["min_first_seen"])
                if "max_last_seen" in filters:
                    query += " AND last_seen <= ?"
                    params.append(filters["max_last_seen"])

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            if not rows:
                logger.warning("No aircraft records found matching filters")
                return 0

            # Write CSV
            fieldnames = [description[0] for description in cursor.description]
            self._write_csv(output_path, fieldnames, rows)

            logger.info(f"Exported {len(rows)} aircraft records to {output_path}")
            return len(rows)

        finally:
            conn.close()

    def export_flight_sessions(
        self,
        output_path: str,
        filters: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Export flight session records to CSV.

        Args:
            output_path: Path where CSV file will be written.
            filters: Optional dictionary with filter criteria:
                - 'aircraft_icao': Filter by ICAO code
                - 'min_start_time': Filter by minimum start_time timestamp
                - 'max_end_time': Filter by maximum end_time timestamp
                - 'completed_only': If True, only export completed sessions (end_time IS NOT NULL)

        Returns:
            Number of records exported.
        """
        conn = self._get_connection()
        try:
            query = "SELECT * FROM flight_session WHERE 1=1"
            params = []

            if filters:
                if "aircraft_icao" in filters:
                    query += " AND aircraft_icao = ?"
                    params.append(filters["aircraft_icao"])
                if "min_start_time" in filters:
                    query += " AND start_time >= ?"
                    params.append(filters["min_start_time"])
                if "max_end_time" in filters:
                    query += " AND end_time <= ?"
                    params.append(filters["max_end_time"])
                if filters.get("completed_only", False):
                    query += " AND end_time IS NOT NULL"

            query += " ORDER BY start_time DESC"
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            if not rows:
                logger.warning("No flight sessions found matching filters")
                return 0

            fieldnames = [description[0] for description in cursor.description]
            self._write_csv(output_path, fieldnames, rows)

            logger.info(f"Exported {len(rows)} flight sessions to {output_path}")
            return len(rows)

        finally:
            conn.close()

    def export_flight_paths(
        self,
        output_path: str,
        filters: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Export flight path records to CSV with optional aircraft and session info.

        Args:
            output_path: Path where CSV file will be written.
            filters: Optional dictionary with filter criteria:
                - 'aircraft_icao': Filter by ICAO code
                - 'session_id': Filter by flight session ID
                - 'min_timestamp': Filter by minimum ts (epoch seconds)
                - 'max_timestamp': Filter by maximum ts (epoch seconds)
                - 'include_aircraft_info': If True, joins with aircraft table for callsign
                - 'include_session_info': If True, joins with flight_session table

        Returns:
            Number of records exported.
        """
        conn = self._get_connection()
        try:
            # Build query with optional joins
            query = "SELECT p.*"
            if filters and filters.get("include_aircraft_info"):
                query += ", a.callsign"
            if filters and filters.get("include_session_info"):
                query += ", fs.start_time as session_start_time, fs.end_time as session_end_time"

            query += " FROM path p"

            if filters and filters.get("include_aircraft_info"):
                query += " LEFT JOIN aircraft a ON p.icao = a.icao"
            if filters and filters.get("include_session_info"):
                query += " LEFT JOIN flight_session fs ON p.session_id = fs.id"

            query += " WHERE 1=1"
            params = []

            if filters:
                if "aircraft_icao" in filters:
                    query += " AND p.icao = ?"
                    params.append(filters["aircraft_icao"])
                if "session_id" in filters:
                    query += " AND p.session_id = ?"
                    params.append(filters["session_id"])
                if "min_timestamp" in filters:
                    query += " AND p.ts >= ?"
                    params.append(filters["min_timestamp"])
                if "max_timestamp" in filters:
                    query += " AND p.ts <= ?"
                    params.append(filters["max_timestamp"])

            query += " ORDER BY p.ts ASC"
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            if not rows:
                logger.warning("No flight paths found matching filters")
                return 0

            fieldnames = [description[0] for description in cursor.description]
            self._write_csv(output_path, fieldnames, rows)

            logger.info(f"Exported {len(rows)} flight paths to {output_path}")
            return len(rows)

        finally:
            conn.close()

    def export_complete_flight_data(
        self,
        output_dir: str,
        aircraft_icao: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, int]:
        """
        Export complete flight data (aircraft, sessions, and paths) to separate CSVs.

        This is useful for exporting a complete dataset or a specific aircraft's
        complete history. Creates three files: aircraft.csv, sessions.csv, paths.csv

        Args:
            output_dir: Directory where CSV files will be written.
            aircraft_icao: If specified, export only data for this aircraft ICAO.
            session_id: If specified, export only data for this flight session.

        Returns:
            Dictionary with export counts for each data type:
                {'aircraft': count, 'sessions': count, 'paths': count}
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        results = {}

        # Export aircraft data
        aircraft_filters = None
        if aircraft_icao:
            aircraft_filters = {"callsign": aircraft_icao}  # This filters by callsign substring
            # If you want exact ICAO match, you'd need to query directly

        aircraft_file = output_path / "aircraft.csv"
        results["aircraft"] = self.export_aircraft(str(aircraft_file), aircraft_filters)

        # Export flight sessions
        session_filters = None
        if aircraft_icao:
            session_filters = {"aircraft_icao": aircraft_icao}
        elif session_id:
            session_filters = {}  # Will filter in export_flight_sessions if needed

        sessions_file = output_path / "sessions.csv"
        results["sessions"] = self.export_flight_sessions(str(sessions_file), session_filters)

        # Export flight paths
        path_filters = {"include_aircraft_info": True, "include_session_info": True}
        if aircraft_icao:
            path_filters["aircraft_icao"] = aircraft_icao
        if session_id:
            path_filters["session_id"] = session_id

        paths_file = output_path / "paths.csv"
        results["paths"] = self.export_flight_paths(str(paths_file), path_filters)

        logger.info(f"Exported complete flight data to {output_dir}: {results}")
        return results

    def export_all_data(self, output_dir: str) -> Dict[str, int]:
        """
        Export all data from database to separate CSV files.

        Creates three files: aircraft.csv, sessions.csv, paths.csv

        Args:
            output_dir: Directory where CSV files will be written.

        Returns:
            Dictionary with export counts for each data type.
        """
        return self.export_complete_flight_data(output_dir)

    @staticmethod
    def _write_csv(
        output_path: str, fieldnames: List[str], rows: List[sqlite3.Row]
    ) -> None:
        """
        Write rows to CSV file.

        Args:
            output_path: Path where CSV file will be written.
            fieldnames: List of column names.
            rows: List of sqlite3.Row objects to write.

        Raises:
            IOError: If file cannot be written.
        """
        try:
            with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    writer.writerow(dict(row))
        except IOError as e:
            logger.error(f"Failed to write CSV to {output_path}: {e}")
            raise

    def export_summary_statistics(self, output_path: str) -> bool:
        """
        Export summary statistics about the database to CSV.

        Includes counts and basic statistics for aircraft, sessions, and paths.

        Args:
            output_path: Path where CSV file will be written.

        Returns:
            True if successful, False otherwise.
        """
        conn = self._get_connection()
        try:
            stats = []

            # Aircraft statistics
            aircraft_count = conn.execute("SELECT COUNT(*) FROM aircraft").fetchone()[0]
            stats.append(("Aircraft Count", aircraft_count))

            # Flight session statistics
            total_sessions = conn.execute("SELECT COUNT(*) FROM flight_session").fetchone()[0]
            completed_sessions = conn.execute(
                "SELECT COUNT(*) FROM flight_session WHERE end_time IS NOT NULL"
            ).fetchone()[0]
            stats.append(("Total Flight Sessions", total_sessions))
            stats.append(("Completed Flight Sessions", completed_sessions))

            # Path statistics
            total_paths = conn.execute("SELECT COUNT(*) FROM path").fetchone()[0]
            stats.append(("Total Path Records", total_paths))

            # Time range
            first_record = conn.execute("SELECT MIN(ts) FROM path").fetchone()[0]
            last_record = conn.execute("SELECT MAX(ts) FROM path").fetchone()[0]
            stats.append(("First Record (epoch)", first_record))
            stats.append(("Last Record (epoch)", last_record))

            if first_record and last_record:
                duration = last_record - first_record
                stats.append(("Duration (seconds)", duration))

            # Write summary CSV
            with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["Statistic", "Value"])
                writer.writerow(["Export Timestamp", datetime.now().isoformat()])
                writer.writerow(["Database Path", self.db_path])
                writer.writerow([])
                writer.writerows(stats)

            logger.info(f"Exported summary statistics to {output_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to export summary statistics: {e}")
            return False
        finally:
            conn.close()


def main():
    """
    Main entry point for CSV export script.

    Exports all data from the aircraft database to CSV files.
    """
    parser = argparse.ArgumentParser(
        description="Export aircraft data from SQLite database to CSV files"
    )
    parser.add_argument(
        "--db",
        default="src/database_api/adsb_data.db",
        help="Path to the SQLite database file (default: src/database_api/adsb_data.db)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="tmp/csv_exports",
        help="Output directory for CSV files (default: tmp/csv_exports)",
    )
    parser.add_argument(
        "--include-stats",
        action="store_true",
        help="Also generate a summary statistics CSV",
    )
    parser.add_argument(
        "--aircraft",
        help="Export only data for specific aircraft ICAO code",
    )
    parser.add_argument(
        "--session",
        help="Export only data for specific flight session ID",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Check if database exists
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: Database file not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    # Initialize exporter
    exporter = CSVExporter(str(db_path))

    # Export data
    print(f"Exporting data from {args.db} to {args.output}/")
    try:
        if args.aircraft or args.session:
            results = exporter.export_complete_flight_data(
                args.output, aircraft_icao=args.aircraft, session_id=args.session
            )
        else:
            results = exporter.export_all_data(args.output)

        print("\nExport successful!")
        print(f"  Aircraft records: {results.get('aircraft', 0)}")
        print(f"  Flight sessions: {results.get('sessions', 0)}")
        print(f"  Flight paths: {results.get('paths', 0)}")

        if args.include_stats:
            stats_file = Path(args.output) / "statistics.csv"
            exporter.export_summary_statistics(str(stats_file))
            print(f"  Summary statistics: {stats_file}")

        print(f"\nFiles written to: {Path(args.output).absolute()}")

    except Exception as e:
        print(f"Error during export: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
