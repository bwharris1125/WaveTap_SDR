"""Tests for the network metrics collection module."""

import csv
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wavetap_utils.network_metrics import (
    NetworkMetricsCollector,
    NetworkMetricSnapshot,
    get_network_collector,
)


class TestNetworkMetricSnapshot:
    """Tests for NetworkMetricSnapshot dataclass."""

    def test_snapshot_creation(self):
        """Test creating a network metric snapshot."""
        snapshot = NetworkMetricSnapshot(
            timestamp="2025-01-01T00:00:00+00:00",
            total_packets=100,
            dropped_packets=5,
            out_of_order_packets=2,
            session_duration_seconds=30.0,
        )

        assert snapshot.timestamp == "2025-01-01T00:00:00+00:00"
        assert snapshot.total_packets == 100
        assert snapshot.dropped_packets == 5
        assert snapshot.out_of_order_packets == 2
        assert snapshot.session_duration_seconds == 30.0

    def test_snapshot_to_dict(self):
        """Test converting snapshot to dictionary."""
        from dataclasses import asdict

        snapshot = NetworkMetricSnapshot(
            timestamp="2025-01-01T00:00:00+00:00",
            total_packets=100,
            dropped_packets=5,
            out_of_order_packets=2,
            session_duration_seconds=30.0,
        )

        snapshot_dict = asdict(snapshot)
        assert snapshot_dict["total_packets"] == 100
        assert snapshot_dict["dropped_packets"] == 5
        assert snapshot_dict["out_of_order_packets"] == 2


class TestNetworkMetricsCollector:
    """Tests for NetworkMetricsCollector class."""

    def test_collector_initialization(self):
        """Test that collector initializes correctly."""
        collector = NetworkMetricsCollector()

        assert collector.total_packets == 0
        assert collector.dropped_packets == 0
        assert collector.out_of_order_packets == 0
        assert len(collector.metrics_history) == 0

    def test_collector_with_logger(self):
        """Test collector with custom logger."""
        mock_logger = MagicMock()
        collector = NetworkMetricsCollector(logger=mock_logger)

        assert collector.logger is mock_logger

    def test_record_packet(self):
        """Test recording packets."""
        collector = NetworkMetricsCollector()

        for _ in range(5):
            collector.record_packet()

        assert collector.total_packets == 5

    def test_record_dropped_packet(self):
        """Test recording dropped packets."""
        collector = NetworkMetricsCollector()

        for _ in range(3):
            collector.record_dropped_packet()

        assert collector.dropped_packets == 3

    def test_record_out_of_order_packet(self):
        """Test recording out-of-order packets."""
        collector = NetworkMetricsCollector()

        for _ in range(2):
            collector.record_out_of_order_packet()

        assert collector.out_of_order_packets == 2

    def test_get_snapshot(self):
        """Test getting a snapshot of current metrics."""
        collector = NetworkMetricsCollector()

        collector.record_packet()
        collector.record_packet()
        collector.record_dropped_packet()

        snapshot = collector.get_snapshot()

        assert snapshot.total_packets == 2
        assert snapshot.dropped_packets == 1
        assert snapshot.out_of_order_packets == 0
        assert snapshot.session_duration_seconds >= 0

    def test_snapshot_added_to_history(self):
        """Test that snapshots are added to history."""
        collector = NetworkMetricsCollector()

        collector.record_packet()
        collector.get_snapshot()

        assert len(collector.metrics_history) == 1

    def test_get_latest(self):
        """Test getting the latest snapshot."""
        collector = NetworkMetricsCollector()

        collector.record_packet()
        snapshot1 = collector.get_snapshot()

        time.sleep(0.01)

        collector.record_packet()
        snapshot2 = collector.get_snapshot()

        latest = collector.get_latest()
        assert latest is snapshot2
        assert latest is not snapshot1

    def test_get_latest_empty(self):
        """Test getting latest when no snapshots exist."""
        collector = NetworkMetricsCollector()

        latest = collector.get_latest()
        assert latest is None

    def test_get_summary(self):
        """Test getting a summary of metrics."""
        collector = NetworkMetricsCollector()

        collector.record_packet()
        collector.record_packet()
        collector.record_dropped_packet()
        collector.record_out_of_order_packet()

        summary = collector.get_summary()

        assert summary["total_packets"] == 2
        assert summary["dropped_packets"] == 1
        assert summary["out_of_order_packets"] == 1
        assert summary["session_duration_seconds"] >= 0

    def test_clear_history(self):
        """Test clearing metrics history."""
        collector = NetworkMetricsCollector()

        collector.record_packet()
        collector.get_snapshot()

        assert len(collector.metrics_history) == 1

        collector.clear_history()

        assert len(collector.metrics_history) == 0

    def test_reset_session(self):
        """Test resetting session metrics."""
        collector = NetworkMetricsCollector()

        collector.record_packet()
        collector.record_dropped_packet()

        assert collector.total_packets == 1
        assert collector.dropped_packets == 1

        collector.reset_session()

        assert collector.total_packets == 0
        assert collector.dropped_packets == 0
        assert collector.out_of_order_packets == 0

    def test_start_csv_logging_default_path(self, tmp_path):
        """Test starting CSV logging with default path."""
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

        collector = NetworkMetricsCollector()
        file_path = collector.start_csv_logging()

        assert "network_metrics_" in file_path
        assert file_path.endswith(".csv")

        collector.stop_csv_logging()

    def test_start_csv_logging_custom_path(self, tmp_path):
        """Test starting CSV logging with custom path."""
        csv_file = tmp_path / "custom_metrics.csv"
        collector = NetworkMetricsCollector()

        file_path = collector.start_csv_logging(str(csv_file))

        assert file_path == str(csv_file)
        assert csv_file.exists()

        collector.stop_csv_logging()

    def test_write_snapshot_to_csv(self, tmp_path):
        """Test writing snapshots to CSV."""
        csv_file = tmp_path / "metrics.csv"
        collector = NetworkMetricsCollector()

        collector.start_csv_logging(str(csv_file))

        collector.record_packet()
        collector.record_packet()
        collector.record_dropped_packet()

        snapshot = collector.get_snapshot()
        collector.write_snapshot_to_csv(snapshot)

        collector.stop_csv_logging()

        # Verify CSV content
        with open(csv_file) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 1
        assert int(rows[0]["total_packets"]) == 2
        assert int(rows[0]["dropped_packets"]) == 1

    def test_periodic_logging(self, tmp_path):
        """Test periodic metric logging."""
        csv_file = tmp_path / "periodic_metrics.csv"
        collector = NetworkMetricsCollector()

        collector.start_csv_logging(str(csv_file))
        collector.start_periodic_logging(interval_seconds=0.1)

        # Record some metrics
        for _ in range(5):
            collector.record_packet()

        # Let periodic logging run for a bit
        time.sleep(0.35)

        collector.stop_periodic_logging()
        collector.stop_csv_logging()

        # Verify CSV has multiple entries
        with open(csv_file) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Should have at least 2-3 snapshots written
        assert len(rows) >= 2

    def test_thread_safety(self):
        """Test thread safety of metric recording."""
        collector = NetworkMetricsCollector()

        def record_packets():
            for _ in range(100):
                collector.record_packet()
                collector.record_dropped_packet()

        threads = [threading.Thread(target=record_packets) for _ in range(5)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        assert collector.total_packets == 500
        assert collector.dropped_packets == 500


class TestGlobalNetworkCollector:
    """Tests for global collector factory function."""

    def test_get_network_collector_creates_instance(self):
        """Test that get_network_collector creates an instance."""
        import wavetap_utils.network_metrics

        wavetap_utils.network_metrics._global_network_collector = None

        collector = get_network_collector()
        assert isinstance(collector, NetworkMetricsCollector)

    def test_get_network_collector_returns_same_instance(self):
        """Test that get_network_collector returns the same instance."""
        import wavetap_utils.network_metrics

        wavetap_utils.network_metrics._global_network_collector = None

        collector1 = get_network_collector()
        collector2 = get_network_collector()

        assert collector1 is collector2

    def test_get_network_collector_with_logger(self):
        """Test get_network_collector with a custom logger."""
        import wavetap_utils.network_metrics

        wavetap_utils.network_metrics._global_network_collector = None

        mock_logger = MagicMock()
        collector = get_network_collector(logger=mock_logger)

        assert collector.logger is mock_logger
