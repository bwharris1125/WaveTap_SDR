"""
Network metrics collection utility for WaveTap.

This module provides utilities for capturing network statistics such as packet counts,
dropped packets, and out-of-order packets. Metrics are periodically written to CSV files
to ensure data persistence even if the application shuts down unexpectedly.
"""

import csv
import logging
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional


@dataclass
class NetworkMetricSnapshot:
    """A point-in-time snapshot of network metrics."""

    timestamp: str
    total_packets: int
    dropped_packets: int
    out_of_order_packets: int
    session_duration_seconds: float


class NetworkMetricsCollector:
    """
    Collects and logs network metrics at regular intervals.

    Maintains counters for packets, dropped packets, and out-of-order packets,
    writing snapshots to a CSV file periodically for data persistence.
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize the network metrics collector.

        Args:
            logger: Optional logger instance. If not provided, a module-level logger is used.
        """
        self.logger = logger or logging.getLogger(__name__)
        self.total_packets = 0
        self.dropped_packets = 0
        self.out_of_order_packets = 0
        self.session_start_time = time.time()
        self.metrics_history = []
        self._lock = threading.Lock()
        self._csv_file: Optional[Path] = None
        self._csv_handle: Optional[object] = None
        self._csv_writer: Optional[csv.DictWriter] = None
        self._collection_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start_csv_logging(self, file_path: Optional[str] = None) -> str:
        """
        Start logging metrics to a CSV file.

        Args:
            file_path: Path to the CSV file. If None, uses default in tmp/metrics/ directory.

        Returns:
            Path to the CSV file being used.
        """
        if file_path is None:
            metrics_dir = Path.cwd() / "tmp" / "metrics"
            metrics_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            file_path = str(metrics_dir / f"network_metrics_{timestamp}.csv")

        self._csv_file = Path(file_path)

        # Open file and create writer
        file_exists = self._csv_file.exists()
        try:
            self._csv_handle = open(self._csv_file, "a", newline="")
            self._csv_writer = csv.DictWriter(
                self._csv_handle,
                fieldnames=[
                    "timestamp",
                    "total_packets",
                    "dropped_packets",
                    "out_of_order_packets",
                    "session_duration_seconds",
                ],
            )
            if not file_exists:
                self._csv_writer.writeheader()
                self._csv_handle.flush()
            self.logger.info("Network metrics CSV logging started: %s", file_path)
        except Exception as e:
            self.logger.error("Failed to start CSV logging: %s", e)
            self._csv_writer = None
            self._csv_handle = None

        return file_path

    def stop_csv_logging(self) -> None:
        """Close the CSV file handle."""
        if self._csv_handle is not None:
            try:
                self._csv_handle.close()
                self.logger.info("Network metrics CSV logging stopped")
            except Exception as e:
                self.logger.error("Error closing CSV file: %s", e)
            finally:
                self._csv_handle = None
                self._csv_writer = None

    def record_packet(self) -> None:
        """Record a single packet received."""
        with self._lock:
            self.total_packets += 1

    def record_dropped_packet(self) -> None:
        """Record a dropped packet."""
        with self._lock:
            self.dropped_packets += 1

    def record_out_of_order_packet(self) -> None:
        """Record an out-of-order packet."""
        with self._lock:
            self.out_of_order_packets += 1

    def get_snapshot(self) -> NetworkMetricSnapshot:
        """
        Get current metrics as a snapshot.

        Returns:
            NetworkMetricSnapshot with current metric values.
        """
        with self._lock:
            session_duration = time.time() - self.session_start_time
            snapshot = NetworkMetricSnapshot(
                timestamp=datetime.now(UTC).isoformat(),
                total_packets=self.total_packets,
                dropped_packets=self.dropped_packets,
                out_of_order_packets=self.out_of_order_packets,
                session_duration_seconds=session_duration,
            )
            self.metrics_history.append(snapshot)
            return snapshot

    def write_snapshot_to_csv(self, snapshot: Optional[NetworkMetricSnapshot] = None) -> None:
        """
        Write a metric snapshot to the CSV file.

        Args:
            snapshot: The snapshot to write. If None, takes a current snapshot.
        """
        if self._csv_writer is None or self._csv_handle is None:
            return

        if snapshot is None:
            snapshot = self.get_snapshot()

        try:
            self._csv_writer.writerow(asdict(snapshot))
            self._csv_handle.flush()
            self.logger.debug(
                "Network metrics snapshot written: %d total, %d dropped, %d out-of-order",
                snapshot.total_packets,
                snapshot.dropped_packets,
                snapshot.out_of_order_packets,
            )
        except Exception as e:
            self.logger.error("Failed to write CSV snapshot: %s", e)

    def start_periodic_logging(self, interval_seconds: float = 10.0) -> None:
        """
        Start a background thread to periodically log metrics.

        Args:
            interval_seconds: Interval in seconds between metric collection.
        """
        if self._collection_thread is not None:
            self.logger.warning("Periodic logging already running")
            return

        self._stop_event.clear()
        self._collection_thread = threading.Thread(
            target=self._periodic_collection_worker,
            args=(interval_seconds,),
            daemon=True,
        )
        self._collection_thread.start()
        self.logger.info("Network metrics periodic logging started (interval: %.1f seconds)", interval_seconds)

    def stop_periodic_logging(self) -> None:
        """Stop the background metrics collection thread."""
        if self._collection_thread is None:
            return

        self._stop_event.set()
        self._collection_thread.join(timeout=5.0)
        self._collection_thread = None
        self.logger.info("Network metrics periodic logging stopped")

    def _periodic_collection_worker(self, interval_seconds: float) -> None:
        """
        Worker thread that periodically collects and writes metrics.

        Args:
            interval_seconds: Interval between collections.
        """
        while not self._stop_event.is_set():
            try:
                snapshot = self.get_snapshot()
                self.write_snapshot_to_csv(snapshot)
            except Exception as e:
                self.logger.error("Error in periodic collection: %s", e)

            self._stop_event.wait(interval_seconds)

    def get_history(self) -> list[NetworkMetricSnapshot]:
        """Get a copy of the metrics history."""
        with self._lock:
            return list(self.metrics_history)

    def get_latest(self) -> Optional[NetworkMetricSnapshot]:
        """Get the most recent metric snapshot."""
        with self._lock:
            return self.metrics_history[-1] if self.metrics_history else None

    def get_summary(self) -> dict:
        """
        Get a summary of current metrics.

        Returns:
            Dictionary with total_packets, dropped_packets, out_of_order_packets, session_duration_seconds.
        """
        with self._lock:
            return {
                "total_packets": self.total_packets,
                "dropped_packets": self.dropped_packets,
                "out_of_order_packets": self.out_of_order_packets,
                "session_duration_seconds": time.time() - self.session_start_time,
            }

    def clear_history(self) -> None:
        """Clear the metrics history."""
        with self._lock:
            self.metrics_history.clear()
        self.logger.debug("Network metrics history cleared")

    def reset_session(self) -> None:
        """Reset all metrics and session timer."""
        with self._lock:
            self.total_packets = 0
            self.dropped_packets = 0
            self.out_of_order_packets = 0
            self.session_start_time = time.time()
        self.logger.info("Network metrics session reset")


# Global collector instance for application-wide use
_global_network_collector: Optional[NetworkMetricsCollector] = None


def get_network_collector(
    logger: Optional[logging.Logger] = None,
) -> NetworkMetricsCollector:
    """
    Get or create the global network metrics collector.

    Args:
        logger: Optional logger instance.

    Returns:
        The global NetworkMetricsCollector instance.
    """
    global _global_network_collector

    if _global_network_collector is None:
        _global_network_collector = NetworkMetricsCollector(logger=logger)

    return _global_network_collector
