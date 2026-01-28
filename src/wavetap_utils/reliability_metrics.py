#!/usr/bin/env python3

"""
Reliability metrics collection utility for WaveTap.

This module provides comprehensive metrics collection for reliability analysis including:
- Network statistics (packet counts, drops, out-of-order)
- Availability metrics (uptime, downtime, MTBF, MTTR)
- Data quality metrics (message success rates, assembly timeouts, failures)
- Performance metrics (latencies, throughput)

Metrics are periodically written to CSV/JSON files for persistence and analysis.
"""

import csv
import json
import logging
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, List, Optional


# ============================================================================
# Network Metrics
# ============================================================================

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


# ============================================================================
# Availability Metrics
# ============================================================================

@dataclass
class OutageEvent:
    """Record of a system outage."""
    start_time: float
    end_time: Optional[float] = None
    component: str = "system"
    reason: str = ""

    @property
    def duration(self) -> Optional[float]:
        """Duration of outage in seconds."""
        if self.end_time is None:
            return None
        return self.end_time - self.start_time


@dataclass
class AvailabilityMetrics:
    """Track system availability over time."""
    uptime_seconds: float = 0.0
    downtime_seconds: float = 0.0
    total_outages: int = 0
    outage_history: List[OutageEvent] = field(default_factory=list)

    @property
    def availability_percent(self) -> float:
        """Calculate availability percentage."""
        total = self.uptime_seconds + self.downtime_seconds
        return (self.uptime_seconds / total * 100) if total > 0 else 0.0

    @property
    def mtbf(self) -> float:
        """Mean Time Between Failures in seconds."""
        if self.total_outages <= 1:
            return self.uptime_seconds
        return self.uptime_seconds / max(self.total_outages - 1, 1)

    @property
    def mttr(self) -> float:
        """Mean Time To Recovery in seconds."""
        if not self.outage_history:
            return 0.0
        completed_outages = [o for o in self.outage_history if o.end_time is not None]
        if not completed_outages:
            return 0.0
        total_downtime = sum(o.duration for o in completed_outages if o.duration)
        return total_downtime / len(completed_outages)


class AvailabilityTracker:
    """Track component availability and outages."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        self.metrics = AvailabilityMetrics()
        self._current_outage: Optional[OutageEvent] = None
        self._session_start = time.time()
        self._last_state = "up"
        self._lock = threading.Lock()

    def record_outage_start(self, component: str = "system", reason: str = ""):
        """Record the start of an outage."""
        with self._lock:
            if self._current_outage is not None:
                self.logger.warning("Outage already in progress, ending previous")
                self.record_outage_end()

            self._current_outage = OutageEvent(
                start_time=time.time(),
                component=component,
                reason=reason
            )
            self.metrics.total_outages += 1
            self._last_state = "down"

        self.logger.warning(f"Outage started for {component}: {reason}")

    def record_outage_end(self):
        """Record the end of an outage."""
        with self._lock:
            if self._current_outage is None:
                self.logger.warning("No active outage to end")
                return

            self._current_outage.end_time = time.time()
            duration = self._current_outage.duration

            self.metrics.downtime_seconds += duration
            self.metrics.outage_history.append(self._current_outage)

            self.logger.info(
                f"Outage ended for {self._current_outage.component}: "
                f"duration {duration:.2f}s"
            )

            self._current_outage = None
            self._last_state = "up"

    def update_uptime(self):
        """Update uptime based on current state."""
        now = time.time()
        with self._lock:
            if self._last_state == "up":
                session_duration = now - self._session_start
                if self._current_outage:
                    # Uptime is from session start to outage start
                    uptime = self._current_outage.start_time - self._session_start
                else:
                    uptime = session_duration - self.metrics.downtime_seconds
                self.metrics.uptime_seconds = max(0, uptime)

    def get_metrics(self) -> AvailabilityMetrics:
        """Get current availability metrics."""
        self.update_uptime()
        with self._lock:
            return self.metrics

    def export_to_json(self, file_path: Optional[str] = None) -> str:
        """Export availability metrics to JSON."""
        if file_path is None:
            metrics_dir = Path.cwd() / "tmp" / "metrics"
            metrics_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            file_path = str(metrics_dir / f"availability_metrics_{timestamp}.json")

        metrics = self.get_metrics()
        data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "uptime_seconds": metrics.uptime_seconds,
            "downtime_seconds": metrics.downtime_seconds,
            "availability_percent": metrics.availability_percent,
            "total_outages": metrics.total_outages,
            "mtbf_seconds": metrics.mtbf,
            "mttr_seconds": metrics.mttr,
            "outage_history": [
                {
                    "start_time": o.start_time,
                    "end_time": o.end_time,
                    "duration": o.duration,
                    "component": o.component,
                    "reason": o.reason,
                }
                for o in metrics.outage_history
            ],
        }

        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)

        self.logger.info(f"Availability metrics exported to {file_path}")
        return file_path


# ============================================================================
# Data Quality Metrics (New)
# ============================================================================

@dataclass
class DataQualityMetrics:
    """Track data quality indicators."""
    messages_received: int = 0
    messages_valid: int = 0
    messages_dropped: int = 0
    messages_malformed: int = 0
    assembly_timeouts: int = 0
    assembly_completed: int = 0
    position_failures: int = 0
    position_successes: int = 0
    stale_cpr_pairs: int = 0

    @property
    def message_success_rate(self) -> float:
        """Calculate message success rate percentage."""
        total = self.messages_received
        return (self.messages_valid / total * 100) if total > 0 else 0.0

    @property
    def assembly_success_rate(self) -> float:
        """Calculate assembly success rate percentage."""
        total = self.assembly_completed + self.assembly_timeouts
        return (self.assembly_completed / total * 100) if total > 0 else 0.0

    @property
    def position_success_rate(self) -> float:
        """Calculate position resolution success rate percentage."""
        total = self.position_successes + self.position_failures
        return (self.position_successes / total * 100) if total > 0 else 0.0


class DataQualityTracker:
    """Track data quality metrics."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        self.metrics = DataQualityMetrics()
        self._lock = threading.Lock()

    def record_message_received(self):
        """Record a message received."""
        with self._lock:
            self.metrics.messages_received += 1

    def record_message_valid(self):
        """Record a valid message."""
        with self._lock:
            self.metrics.messages_valid += 1

    def record_message_dropped(self):
        """Record a dropped message."""
        with self._lock:
            self.metrics.messages_dropped += 1

    def record_message_malformed(self):
        """Record a malformed message."""
        with self._lock:
            self.metrics.messages_malformed += 1

    def record_assembly_timeout(self):
        """Record an assembly timeout."""
        with self._lock:
            self.metrics.assembly_timeouts += 1

    def record_assembly_completed(self):
        """Record a completed assembly."""
        with self._lock:
            self.metrics.assembly_completed += 1

    def record_position_failure(self):
        """Record a position calculation failure."""
        with self._lock:
            self.metrics.position_failures += 1

    def record_position_success(self):
        """Record a successful position calculation."""
        with self._lock:
            self.metrics.position_successes += 1

    def record_stale_cpr_pair(self):
        """Record a stale CPR pair."""
        with self._lock:
            self.metrics.stale_cpr_pairs += 1

    def get_metrics(self) -> DataQualityMetrics:
        """Get current data quality metrics."""
        with self._lock:
            return self.metrics

    def export_to_json(self, file_path: Optional[str] = None) -> str:
        """Export data quality metrics to JSON."""
        if file_path is None:
            metrics_dir = Path.cwd() / "tmp" / "metrics"
            metrics_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            file_path = str(metrics_dir / f"data_quality_metrics_{timestamp}.json")

        metrics = self.get_metrics()
        data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "messages_received": metrics.messages_received,
            "messages_valid": metrics.messages_valid,
            "messages_dropped": metrics.messages_dropped,
            "messages_malformed": metrics.messages_malformed,
            "message_success_rate_percent": metrics.message_success_rate,
            "assembly_completed": metrics.assembly_completed,
            "assembly_timeouts": metrics.assembly_timeouts,
            "assembly_success_rate_percent": metrics.assembly_success_rate,
            "position_successes": metrics.position_successes,
            "position_failures": metrics.position_failures,
            "position_success_rate_percent": metrics.position_success_rate,
            "stale_cpr_pairs": metrics.stale_cpr_pairs,
        }

        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)

        self.logger.info(f"Data quality metrics exported to {file_path}")
        return file_path


# ============================================================================
# Performance Metrics
# ============================================================================

@dataclass
class PerformanceMetrics:
    """Track performance indicators."""
    message_latencies_ms: deque = field(default_factory=lambda: deque(maxlen=1000))
    db_write_latencies_ms: deque = field(default_factory=lambda: deque(maxlen=1000))
    assembly_times_ms: deque = field(default_factory=lambda: deque(maxlen=1000))

    def add_message_latency(self, latency_ms: float):
        """Add a message latency sample."""
        self.message_latencies_ms.append(latency_ms)

    def add_db_write_latency(self, latency_ms: float):
        """Add a database write latency sample."""
        self.db_write_latencies_ms.append(latency_ms)

    def add_assembly_time(self, assembly_ms: float):
        """Add an assembly time sample."""
        self.assembly_times_ms.append(assembly_ms)

    def get_latency_stats(self, latencies: deque) -> Dict[str, float]:
        """Calculate statistics for a latency queue."""
        if not latencies:
            return {
                "count": 0,
                "min": 0.0,
                "max": 0.0,
                "mean": 0.0,
                "p50": 0.0,
                "p95": 0.0,
                "p99": 0.0,
            }

        sorted_latencies = sorted(latencies)
        count = len(sorted_latencies)

        return {
            "count": count,
            "min": sorted_latencies[0],
            "max": sorted_latencies[-1],
            "mean": sum(sorted_latencies) / count,
            "p50": sorted_latencies[int(count * 0.50)],
            "p95": sorted_latencies[int(count * 0.95)],
            "p99": sorted_latencies[int(count * 0.99)],
        }

    @property
    def message_latency_stats(self) -> Dict[str, float]:
        """Get message latency statistics."""
        return self.get_latency_stats(self.message_latencies_ms)

    @property
    def db_write_latency_stats(self) -> Dict[str, float]:
        """Get database write latency statistics."""
        return self.get_latency_stats(self.db_write_latencies_ms)

    @property
    def assembly_time_stats(self) -> Dict[str, float]:
        """Get assembly time statistics."""
        return self.get_latency_stats(self.assembly_times_ms)


class PerformanceTracker:
    """Track performance metrics."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        self.metrics = PerformanceMetrics()
        self._lock = threading.Lock()

    def record_message_latency(self, latency_ms: float):
        """Record message processing latency."""
        with self._lock:
            self.metrics.add_message_latency(latency_ms)

    def record_db_write_latency(self, latency_ms: float):
        """Record database write latency."""
        with self._lock:
            self.metrics.add_db_write_latency(latency_ms)

    def record_assembly_time(self, assembly_ms: float):
        """Record message assembly time."""
        with self._lock:
            self.metrics.add_assembly_time(assembly_ms)

    def get_metrics(self) -> PerformanceMetrics:
        """Get current performance metrics."""
        with self._lock:
            return self.metrics

    def export_to_json(self, file_path: Optional[str] = None) -> str:
        """Export performance metrics to JSON."""
        if file_path is None:
            metrics_dir = Path.cwd() / "tmp" / "metrics"
            metrics_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            file_path = str(metrics_dir / f"performance_metrics_{timestamp}.json")

        metrics = self.get_metrics()
        data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "message_latency": metrics.message_latency_stats,
            "db_write_latency": metrics.db_write_latency_stats,
            "assembly_time": metrics.assembly_time_stats,
        }

        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)

        self.logger.info(f"Performance metrics exported to {file_path}")
        return file_path
