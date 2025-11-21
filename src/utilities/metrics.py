"""
Passive metrics collection for WaveTap services.

This module provides utilities for gathering performance and network metrics
without affecting the operation of existing services. All collection is passive
and non-intrusive.
"""

import json
import logging
import platform
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Optional

import psutil


@dataclass
class TCPMetricSnapshot:
    """A point-in-time snapshot of TCP metrics."""

    timestamp: str
    dropped_packets: int
    retransmitted_packets: int
    outoforder_packets: int


class DroppedTCPPacketsCollector:
    """
    Passively collects TCP dropped packets metrics from /proc/net/tcp.

    This collector reads system-level TCP statistics without affecting
    application behavior. It tracks dropped packets over time by querying
    the kernel's network statistics.
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize the collector.

        Args:
            logger: Optional logger instance. If not provided, a module-level logger is used.
        """
        self.logger = logger or logging.getLogger(__name__)
        self.metrics_history: list[TCPMetricSnapshot] = []
        self._lock = Lock()
        self._last_collected_dropped = 0
        self._delta_dropped = 0

    @staticmethod
    def _read_tcp_stats_from_proc() -> tuple[int, int, int]:
        """
        Read TCP statistics from /proc/net/tcp.

        Returns:
            Tuple of (dropped_packets, retransmitted_packets, outoforder_packets)
            Returns (0, 0, 0) if unable to read the statistics.
        """
        tcp_stats_path = Path("/proc/net/tcp")
        if not tcp_stats_path.exists():
            return 0, 0, 0

        try:
            with open(tcp_stats_path, "r") as f:
                content = f.read()

            # Parse /proc/net/tcp format
            # Each line represents a connection with format:
            # sl local_address rem_address st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode
            dropped = 0
            retransmitted = 0
            outoforder = 0

            lines = content.strip().split("\n")
            # Skip header
            if lines:
                lines = lines[1:]

            for line in lines:
                fields = line.split()
                if len(fields) >= 10:
                    # tr field (index 6) contains retransmit info
                    tr_field = fields[6]
                    # When retransmit is active, format is "retransmit_timeout:timer_value"
                    if ":" in tr_field:
                        try:
                            retransmit_val = int(tr_field.split(":")[0], 16)
                            retransmitted += retransmit_val
                        except (ValueError, IndexError):
                            pass

            # Try to read from /proc/net/netstat for more detailed stats
            netstat_path = Path("/proc/net/netstat")
            if netstat_path.exists():
                with open(netstat_path, "r") as f:
                    netstat_lines = f.readlines()

                # Look for TcpExt section
                tcp_ext_idx = None
                for i, line in enumerate(netstat_lines):
                    if line.startswith("TcpExt:"):
                        tcp_ext_idx = i
                        break

                if tcp_ext_idx is not None and tcp_ext_idx + 1 < len(netstat_lines):
                    header_line = netstat_lines[tcp_ext_idx]
                    data_line = netstat_lines[tcp_ext_idx + 1]

                    header_fields = header_line.split()
                    data_fields = data_line.split()

                    # Find TCPListen, ListenDrops, ListenOverflows, TCPDropped, etc.
                    for field_idx, field_name in enumerate(header_fields[1:], 1):
                        if field_name == "TCPListen" and field_idx < len(data_fields):
                            try:
                                dropped += int(data_fields[field_idx])
                            except (ValueError, IndexError):
                                pass
                        elif field_name == "ListenDrops" and field_idx < len(data_fields):
                            try:
                                dropped += int(data_fields[field_idx])
                            except (ValueError, IndexError):
                                pass
                        elif field_name == "ListenOverflows" and field_idx < len(data_fields):
                            try:
                                dropped += int(data_fields[field_idx])
                            except (ValueError, IndexError):
                                pass
                        elif field_name == "TCPDropped" and field_idx < len(data_fields):
                            try:
                                dropped += int(data_fields[field_idx])
                            except (ValueError, IndexError):
                                pass
                        elif field_name == "TCPOFOQueue" and field_idx < len(data_fields):
                            try:
                                outoforder += int(data_fields[field_idx])
                            except (ValueError, IndexError):
                                pass

            return dropped, retransmitted, outoforder

        except (OSError, IOError) as e:
            logging.debug("Failed to read TCP stats: %s", e)
            return 0, 0, 0

    def collect(self) -> TCPMetricSnapshot:
        """
        Collect current TCP metrics and add them to the history.

        Returns:
            TCPMetricSnapshot with current metrics.
        """
        dropped, retransmitted, outoforder = self._read_tcp_stats_from_proc()

        # Calculate delta for dropped packets
        delta_dropped = dropped - self._last_collected_dropped
        self._last_collected_dropped = dropped
        self._delta_dropped = delta_dropped

        timestamp = datetime.now(UTC).isoformat()
        snapshot = TCPMetricSnapshot(
            timestamp=timestamp,
            dropped_packets=dropped,
            retransmitted_packets=retransmitted,
            outoforder_packets=outoforder,
        )

        with self._lock:
            self.metrics_history.append(snapshot)

        self.logger.debug(
            "TCP metrics collected: dropped=%d (delta=%d), "
            "retransmitted=%d, outoforder=%d",
            dropped,
            delta_dropped,
            retransmitted,
            outoforder,
        )

        return snapshot

    def get_history(self) -> list[TCPMetricSnapshot]:
        """Get a copy of the metrics history."""
        with self._lock:
            return list(self.metrics_history)

    def get_latest(self) -> Optional[TCPMetricSnapshot]:
        """Get the most recent metric snapshot."""
        with self._lock:
            return self.metrics_history[-1] if self.metrics_history else None

    def get_delta_dropped(self) -> int:
        """Get the delta (change) in dropped packets since last collection."""
        return self._delta_dropped

    def export_to_json(self, file_path: Optional[str] = None) -> str:
        """
        Export metrics history to JSON format.

        Args:
            file_path: Optional path to write JSON to file. If not provided,
                      returns JSON string only.

        Returns:
            JSON string representation of metrics history.
        """
        with self._lock:
            json_data = json.dumps(
                [asdict(m) for m in self.metrics_history],
                indent=2,
            )

        if file_path:
            try:
                with open(file_path, "w") as f:
                    f.write(json_data)
                self.logger.info("Metrics exported to %s", file_path)
            except (OSError, IOError) as e:
                self.logger.error("Failed to export metrics to %s: %s", file_path, e)

        return json_data

    def clear_history(self) -> None:
        """Clear the metrics history."""
        with self._lock:
            self.metrics_history.clear()
        self._last_collected_dropped = 0
        self._delta_dropped = 0
        self.logger.debug("Metrics history cleared")


# Global collector instance for application-wide use
_global_tcp_collector: Optional[DroppedTCPPacketsCollector] = None


def get_tcp_collector(
    logger: Optional[logging.Logger] = None,
) -> DroppedTCPPacketsCollector:
    """
    Get or create the global TCP metrics collector.

    Args:
        logger: Optional logger instance.

    Returns:
        The global DroppedTCPPacketsCollector instance.
    """
    global _global_tcp_collector

    if _global_tcp_collector is None:
        _global_tcp_collector = DroppedTCPPacketsCollector(logger=logger)

    return _global_tcp_collector


@dataclass
class MessageAssemblySnapshot:
    """A snapshot of message assembly time metrics."""

    timestamp: str
    icao: str
    assembly_time_ms: float
    fields_completed: list[str]


class ADSBMessageAssemblyCollector:
    """
    Passively collects metrics on how long it takes for ADS-B messages
    to have all fields populated, measured from first message received
    (by ICAO) to when all key fields are present.
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize the collector.

        Args:
            logger: Optional logger instance. If not provided, a module-level logger is used.
        """
        self.logger = logger or logging.getLogger(__name__)
        self.metrics_history: list[MessageAssemblySnapshot] = []
        self._lock = Lock()
        self.required_fields = {"callsign", "position", "altitude", "velocity"}

    def record_assembly_complete(
        self,
        icao: str,
        assembly_time_ms: float,
        fields_completed: Optional[list[str]] = None,
    ) -> MessageAssemblySnapshot:
        """
        Record when an aircraft's message assembly is complete.

        Args:
            icao: Aircraft ICAO address.
            assembly_time_ms: Time in milliseconds from first message to complete assembly.
            fields_completed: List of completed fields. If None, assumes all required fields.

        Returns:
            MessageAssemblySnapshot with the recorded metric.
        """
        if fields_completed is None:
            fields_completed = list(self.required_fields)

        timestamp = datetime.now(UTC).isoformat()
        snapshot = MessageAssemblySnapshot(
            timestamp=timestamp,
            icao=icao,
            assembly_time_ms=assembly_time_ms,
            fields_completed=fields_completed,
        )

        with self._lock:
            self.metrics_history.append(snapshot)

        self.logger.debug(
            "Message assembly complete for %s: %.2fms with fields %s",
            icao,
            assembly_time_ms,
            ", ".join(fields_completed),
        )

        return snapshot

    def get_history(self) -> list[MessageAssemblySnapshot]:
        """Get a copy of the metrics history."""
        with self._lock:
            return list(self.metrics_history)

    def get_statistics(self) -> dict:
        """
        Get aggregate statistics on message assembly times.

        Returns:
            Dictionary with min, max, mean, median, and total count.
        """
        with self._lock:
            if not self.metrics_history:
                return {
                    "count": 0,
                    "min_ms": None,
                    "max_ms": None,
                    "mean_ms": None,
                    "median_ms": None,
                }

            times = [s.assembly_time_ms for s in self.metrics_history]
            times_sorted = sorted(times)

            return {
                "count": len(times),
                "min_ms": min(times),
                "max_ms": max(times),
                "mean_ms": sum(times) / len(times),
                "median_ms": times_sorted[len(times) // 2],
            }

    def export_to_json(self, file_path: Optional[str] = None) -> str:
        """
        Export metrics history to JSON format.

        Args:
            file_path: Optional path to write JSON to file. If not provided,
                      returns JSON string only.

        Returns:
            JSON string representation of metrics history.
        """
        with self._lock:
            json_data = json.dumps(
                [asdict(m) for m in self.metrics_history],
                indent=2,
            )

        if file_path:
            try:
                with open(file_path, "w") as f:
                    f.write(json_data)
                self.logger.info("Message assembly metrics exported to %s", file_path)
            except (OSError, IOError) as e:
                self.logger.error("Failed to export metrics to %s: %s", file_path, e)

        return json_data

    def clear_history(self) -> None:
        """Clear the metrics history."""
        with self._lock:
            self.metrics_history.clear()
        self.logger.debug("Message assembly metrics history cleared")


# Global collector instance for message assembly metrics
_global_assembly_collector: Optional[ADSBMessageAssemblyCollector] = None


def get_assembly_collector(
    logger: Optional[logging.Logger] = None,
) -> ADSBMessageAssemblyCollector:
    """
    Get or create the global message assembly metrics collector.

    Args:
        logger: Optional logger instance.

    Returns:
        The global ADSBMessageAssemblyCollector instance.
    """
    global _global_assembly_collector

    if _global_assembly_collector is None:
        _global_assembly_collector = ADSBMessageAssemblyCollector(logger=logger)

    return _global_assembly_collector


@dataclass
class SystemResourceSnapshot:
    """A snapshot of system resource usage metrics."""

    timestamp: str
    os_name: str
    os_version: str
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    memory_available_mb: float


class SystemResourceCollector:
    """
    Passively collects system resource metrics (CPU and memory usage) with OS information.

    This collector gathers performance metrics to help evaluate application
    performance across different systems (e.g., Windows vs Raspberry Pi).
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize the collector.

        Args:
            logger: Optional logger instance. If not provided, a module-level logger is used.
        """
        self.logger = logger or logging.getLogger(__name__)
        self.metrics_history: list[SystemResourceSnapshot] = []
        self._lock = Lock()
        self._os_info = self._get_os_info()

    @staticmethod
    def _get_os_info() -> tuple[str, str]:
        """
        Get OS name and version information.

        Returns:
            Tuple of (os_name, os_version). e.g., ('Linux', '5.10.0-8-arm64')
        """
        try:
            os_name = platform.system()  # 'Linux', 'Windows', 'Darwin' (macOS)
            os_version = platform.release()
            return os_name, os_version
        except Exception:
            return "Unknown", "Unknown"

    def collect(self) -> SystemResourceSnapshot:
        """
        Collect current system resource metrics and add them to the history.

        Returns:
            SystemResourceSnapshot with current metrics.
        """
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory_info = psutil.virtual_memory()
            memory_percent = memory_info.percent
            memory_used_mb = memory_info.used / (1024 * 1024)
            memory_available_mb = memory_info.available / (1024 * 1024)
        except Exception as e:
            self.logger.warning("Failed to collect system resources: %s", e)
            cpu_percent = 0.0
            memory_percent = 0.0
            memory_used_mb = 0.0
            memory_available_mb = 0.0

        timestamp = datetime.now(UTC).isoformat()
        snapshot = SystemResourceSnapshot(
            timestamp=timestamp,
            os_name=self._os_info[0],
            os_version=self._os_info[1],
            cpu_percent=cpu_percent,
            memory_percent=memory_percent,
            memory_used_mb=memory_used_mb,
            memory_available_mb=memory_available_mb,
        )

        with self._lock:
            self.metrics_history.append(snapshot)

        self.logger.debug(
            "System resources collected: OS=%s %s, CPU=%.1f%%, "
            "Memory=%.1f%% (used=%.1fMB, available=%.1fMB)",
            self._os_info[0],
            self._os_info[1],
            cpu_percent,
            memory_percent,
            memory_used_mb,
            memory_available_mb,
        )

        return snapshot

    def get_history(self) -> list[SystemResourceSnapshot]:
        """Get a copy of the metrics history."""
        with self._lock:
            return list(self.metrics_history)

    def get_latest(self) -> Optional[SystemResourceSnapshot]:
        """Get the most recent metric snapshot."""
        with self._lock:
            return self.metrics_history[-1] if self.metrics_history else None

    def get_statistics(self) -> dict:
        """
        Get aggregate statistics on system resource usage.

        Returns:
            Dictionary with average and peak CPU/memory usage.
        """
        with self._lock:
            if not self.metrics_history:
                return {
                    "count": 0,
                    "os_name": self._os_info[0],
                    "os_version": self._os_info[1],
                    "cpu_avg_percent": None,
                    "cpu_peak_percent": None,
                    "memory_avg_percent": None,
                    "memory_peak_percent": None,
                    "memory_peak_used_mb": None,
                }

            cpu_values = [s.cpu_percent for s in self.metrics_history]
            memory_values = [s.memory_percent for s in self.metrics_history]
            memory_used_values = [s.memory_used_mb for s in self.metrics_history]

            return {
                "count": len(self.metrics_history),
                "os_name": self._os_info[0],
                "os_version": self._os_info[1],
                "cpu_avg_percent": sum(cpu_values) / len(cpu_values),
                "cpu_peak_percent": max(cpu_values),
                "memory_avg_percent": sum(memory_values) / len(memory_values),
                "memory_peak_percent": max(memory_values),
                "memory_peak_used_mb": max(memory_used_values),
            }

    def export_to_json(self, file_path: Optional[str] = None) -> str:
        """
        Export metrics history to JSON format.

        Args:
            file_path: Optional path to write JSON to file. If not provided,
                      returns JSON string only.

        Returns:
            JSON string representation of metrics history.
        """
        with self._lock:
            json_data = json.dumps(
                [asdict(m) for m in self.metrics_history],
                indent=2,
            )

        if file_path:
            try:
                with open(file_path, "w") as f:
                    f.write(json_data)
                self.logger.info("System resource metrics exported to %s", file_path)
            except (OSError, IOError) as e:
                self.logger.error("Failed to export metrics to %s: %s", file_path, e)

        return json_data

    def clear_history(self) -> None:
        """Clear the metrics history."""
        with self._lock:
            self.metrics_history.clear()
        self.logger.debug("System resource metrics history cleared")


# Global collector instance for system resource metrics
_global_system_resource_collector: Optional[SystemResourceCollector] = None


def get_system_resource_collector(
    logger: Optional[logging.Logger] = None,
) -> SystemResourceCollector:
    """
    Get or create the global system resource metrics collector.

    Args:
        logger: Optional logger instance.

    Returns:
        The global SystemResourceCollector instance.
    """
    global _global_system_resource_collector

    if _global_system_resource_collector is None:
        _global_system_resource_collector = SystemResourceCollector(logger=logger)

    return _global_system_resource_collector
