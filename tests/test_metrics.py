"""Tests for the metrics collection module."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from utilities.metrics import (
    ADSBMessageAssemblyCollector,
    DroppedTCPPacketsCollector,
    MessageAssemblySnapshot,
    SystemResourceCollector,
    SystemResourceSnapshot,
    TCPMetricSnapshot,
    get_assembly_collector,
    get_system_resource_collector,
    get_tcp_collector,
)


class TestTCPMetricSnapshot:
    """Tests for TCPMetricSnapshot dataclass."""

    def test_snapshot_creation(self):
        """Test creating a metric snapshot."""
        snapshot = TCPMetricSnapshot(
            timestamp="2025-01-01T00:00:00+00:00",
            dropped_packets=10,
            retransmitted_packets=5,
            outoforder_packets=2,
        )
        assert snapshot.dropped_packets == 10
        assert snapshot.retransmitted_packets == 5
        assert snapshot.outoforder_packets == 2

    def test_snapshot_to_dict(self):
        """Test converting snapshot to dictionary."""
        from dataclasses import asdict
        snapshot = TCPMetricSnapshot(
            timestamp="2025-01-01T00:00:00+00:00",
            dropped_packets=10,
            retransmitted_packets=5,
            outoforder_packets=2,
        )
        snap_dict = asdict(snapshot)
        assert snap_dict["dropped_packets"] == 10
        assert snap_dict["retransmitted_packets"] == 5


class TestDroppedTCPPacketsCollector:
    """Tests for DroppedTCPPacketsCollector."""

    def test_collector_initialization(self):
        """Test collector can be initialized."""
        collector = DroppedTCPPacketsCollector()
        assert collector.metrics_history == []
        assert collector._last_collected_dropped == 0
        assert collector._delta_dropped == 0

    def test_collector_with_logger(self):
        """Test collector can be initialized with a logger."""
        mock_logger = MagicMock()
        collector = DroppedTCPPacketsCollector(logger=mock_logger)
        assert collector.logger is mock_logger

    @patch.object(DroppedTCPPacketsCollector, '_read_tcp_stats_from_proc')
    def test_collect_metrics(self, mock_read):
        """Test collecting metrics."""
        mock_read.return_value = (100, 50, 10)

        collector = DroppedTCPPacketsCollector()
        snapshot = collector.collect()

        assert snapshot.dropped_packets == 100
        assert snapshot.retransmitted_packets == 50
        assert snapshot.outoforder_packets == 10
        assert len(collector.metrics_history) == 1

    @patch.object(DroppedTCPPacketsCollector, '_read_tcp_stats_from_proc')
    def test_collect_multiple_times(self, mock_read):
        """Test collecting metrics multiple times."""
        mock_read.side_effect = [(100, 50, 10), (105, 52, 11)]

        collector = DroppedTCPPacketsCollector()
        snapshot1 = collector.collect()
        snapshot2 = collector.collect()

        assert len(collector.metrics_history) == 2
        assert snapshot1.dropped_packets == 100
        assert snapshot2.dropped_packets == 105

    @patch.object(DroppedTCPPacketsCollector, '_read_tcp_stats_from_proc')
    def test_delta_dropped_packets(self, mock_read):
        """Test delta calculation for dropped packets."""
        mock_read.side_effect = [(100, 0, 0), (105, 0, 0), (110, 0, 0)]

        collector = DroppedTCPPacketsCollector()

        collector.collect()
        assert collector.get_delta_dropped() == 100  # Initial: 100 - 0 = 100

        collector.collect()
        assert collector.get_delta_dropped() == 5  # Delta: 105 - 100 = 5

        collector.collect()
        assert collector.get_delta_dropped() == 5  # Delta: 110 - 105 = 5

    @patch.object(DroppedTCPPacketsCollector, '_read_tcp_stats_from_proc')
    def test_get_history(self, mock_read):
        """Test retrieving metrics history."""
        mock_read.side_effect = [(100, 50, 10), (105, 52, 11)]

        collector = DroppedTCPPacketsCollector()
        collector.collect()
        collector.collect()

        history = collector.get_history()
        assert len(history) == 2

    @patch.object(DroppedTCPPacketsCollector, '_read_tcp_stats_from_proc')
    def test_get_latest(self, mock_read):
        """Test retrieving latest metrics."""
        mock_read.side_effect = [(100, 50, 10), (105, 52, 11)]

        collector = DroppedTCPPacketsCollector()
        collector.collect()
        latest1 = collector.get_latest()

        collector.collect()
        latest2 = collector.get_latest()

        assert latest1.dropped_packets == 100
        assert latest2.dropped_packets == 105

    @patch.object(DroppedTCPPacketsCollector, '_read_tcp_stats_from_proc')
    def test_get_latest_empty(self, mock_read):
        """Test get_latest returns None for empty history."""
        collector = DroppedTCPPacketsCollector()
        assert collector.get_latest() is None

    @patch.object(DroppedTCPPacketsCollector, '_read_tcp_stats_from_proc')
    def test_export_to_json_string(self, mock_read):
        """Test exporting metrics as JSON string."""
        mock_read.side_effect = [(100, 50, 10), (105, 52, 11)]

        collector = DroppedTCPPacketsCollector()
        collector.collect()
        collector.collect()

        json_str = collector.export_to_json()
        data = json.loads(json_str)

        assert len(data) == 2
        assert data[0]["dropped_packets"] == 100
        assert data[1]["dropped_packets"] == 105

    @patch.object(DroppedTCPPacketsCollector, '_read_tcp_stats_from_proc')
    def test_export_to_json_file(self, mock_read):
        """Test exporting metrics to a file."""
        mock_read.side_effect = [(100, 50, 10), (105, 52, 11)]

        collector = DroppedTCPPacketsCollector()
        collector.collect()
        collector.collect()

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            temp_path = f.name

        try:
            collector.export_to_json(temp_path)

            with open(temp_path, 'r') as f:
                data = json.load(f)

            assert len(data) == 2
            assert data[0]["dropped_packets"] == 100
        finally:
            Path(temp_path).unlink(missing_ok=True)

    @patch.object(DroppedTCPPacketsCollector, '_read_tcp_stats_from_proc')
    def test_clear_history(self, mock_read):
        """Test clearing metrics history."""
        mock_read.side_effect = [(100, 50, 10), (105, 52, 11)]

        collector = DroppedTCPPacketsCollector()
        collector.collect()
        collector.collect()
        assert len(collector.metrics_history) == 2

        collector.clear_history()
        assert len(collector.metrics_history) == 0
        assert collector._last_collected_dropped == 0
        assert collector._delta_dropped == 0

    def test_read_tcp_stats_no_proc(self):
        """Test reading stats when /proc/net/tcp doesn't exist."""
        with patch('pathlib.Path.exists', return_value=False):
            stats = DroppedTCPPacketsCollector._read_tcp_stats_from_proc()
            assert stats == (0, 0, 0)

    @patch('builtins.open', create=True)
    @patch('pathlib.Path.exists')
    def test_read_tcp_stats_from_proc_error(self, mock_exists, mock_open):
        """Test error handling when reading /proc/net/tcp."""
        mock_exists.return_value = True
        mock_open.side_effect = OSError("Permission denied")

        stats = DroppedTCPPacketsCollector._read_tcp_stats_from_proc()
        assert stats == (0, 0, 0)

    def test_thread_safety(self):
        """Test that collector is thread-safe."""
        import threading

        collector = DroppedTCPPacketsCollector()

        with patch.object(DroppedTCPPacketsCollector, '_read_tcp_stats_from_proc') as mock_read:
            mock_read.return_value = (100, 50, 10)

            def collect_in_thread():
                for _ in range(10):
                    collector.collect()

            threads = [threading.Thread(target=collect_in_thread) for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # All collections should be recorded
            assert len(collector.metrics_history) == 30


class TestGlobalCollector:
    """Tests for global collector factory function."""

    def test_get_tcp_collector_creates_instance(self):
        """Test that get_tcp_collector creates an instance."""
        # Reset global state
        import utilities.metrics
        utilities.metrics._global_tcp_collector = None

        collector = get_tcp_collector()
        assert isinstance(collector, DroppedTCPPacketsCollector)

    def test_get_tcp_collector_returns_same_instance(self):
        """Test that get_tcp_collector returns the same instance."""
        import utilities.metrics
        utilities.metrics._global_tcp_collector = None

        collector1 = get_tcp_collector()
        collector2 = get_tcp_collector()

        assert collector1 is collector2

    def test_get_tcp_collector_with_logger(self):
        """Test get_tcp_collector with a custom logger."""
        import utilities.metrics
        utilities.metrics._global_tcp_collector = None

        mock_logger = MagicMock()
        collector = get_tcp_collector(logger=mock_logger)

        assert collector.logger is mock_logger


class TestMessageAssemblySnapshot:
    """Tests for MessageAssemblySnapshot dataclass."""

    def test_snapshot_creation(self):
        """Test creating a message assembly snapshot."""
        snapshot = MessageAssemblySnapshot(
            timestamp="2025-01-01T00:00:00+00:00",
            icao="ABC123",
            assembly_time_ms=150.5,
            fields_completed=["callsign", "position"],
        )
        assert snapshot.icao == "ABC123"
        assert snapshot.assembly_time_ms == 150.5
        assert len(snapshot.fields_completed) == 2


class TestADSBMessageAssemblyCollector:
    """Tests for ADSBMessageAssemblyCollector."""

    def test_collector_initialization(self):
        """Test collector can be initialized."""
        collector = ADSBMessageAssemblyCollector()
        assert collector.metrics_history == []

    def test_record_assembly_complete(self):
        """Test recording message assembly completion."""
        collector = ADSBMessageAssemblyCollector()

        snapshot = collector.record_assembly_complete(
            icao="ABC123",
            assembly_time_ms=125.0,
            fields_completed=["callsign", "position", "altitude", "velocity"],
        )

        assert snapshot.icao == "ABC123"
        assert snapshot.assembly_time_ms == 125.0
        assert len(collector.metrics_history) == 1

    def test_record_multiple_assemblies(self):
        """Test recording multiple aircraft assembly completions."""
        collector = ADSBMessageAssemblyCollector()

        collector.record_assembly_complete("ABC123", 100.0)
        collector.record_assembly_complete("DEF456", 250.5)
        collector.record_assembly_complete("GHI789", 75.3)

        assert len(collector.metrics_history) == 3
        assert collector.metrics_history[0].icao == "ABC123"
        assert collector.metrics_history[1].icao == "DEF456"

    def test_get_statistics(self):
        """Test getting aggregate statistics."""
        collector = ADSBMessageAssemblyCollector()

        # Record some assembly times
        collector.record_assembly_complete("ABC123", 100.0)
        collector.record_assembly_complete("DEF456", 200.0)
        collector.record_assembly_complete("GHI789", 150.0)

        stats = collector.get_statistics()

        assert stats["count"] == 3
        assert stats["min_ms"] == 100.0
        assert stats["max_ms"] == 200.0
        assert stats["mean_ms"] == 150.0
        assert stats["median_ms"] == 150.0

    def test_get_statistics_empty(self):
        """Test get_statistics with empty history."""
        collector = ADSBMessageAssemblyCollector()

        stats = collector.get_statistics()

        assert stats["count"] == 0
        assert stats["min_ms"] is None
        assert stats["max_ms"] is None
        assert stats["mean_ms"] is None

    def test_export_to_json_string(self):
        """Test exporting assembly metrics as JSON string."""
        collector = ADSBMessageAssemblyCollector()

        collector.record_assembly_complete("ABC123", 100.0)
        collector.record_assembly_complete("DEF456", 200.0)

        json_str = collector.export_to_json()
        data = json.loads(json_str)

        assert len(data) == 2
        assert data[0]["icao"] == "ABC123"
        assert data[1]["icao"] == "DEF456"

    def test_export_to_json_file(self):
        """Test exporting assembly metrics to a file."""
        collector = ADSBMessageAssemblyCollector()

        collector.record_assembly_complete("ABC123", 100.0)
        collector.record_assembly_complete("DEF456", 200.0)

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            temp_path = f.name

        try:
            collector.export_to_json(temp_path)

            with open(temp_path, 'r') as f:
                data = json.load(f)

            assert len(data) == 2
            assert data[0]["icao"] == "ABC123"
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_clear_history(self):
        """Test clearing metrics history."""
        collector = ADSBMessageAssemblyCollector()

        collector.record_assembly_complete("ABC123", 100.0)
        collector.record_assembly_complete("DEF456", 200.0)
        assert len(collector.metrics_history) == 2

        collector.clear_history()
        assert len(collector.metrics_history) == 0


class TestGlobalAssemblyCollector:
    """Tests for global assembly collector factory function."""

    def test_get_assembly_collector_creates_instance(self):
        """Test that get_assembly_collector creates an instance."""
        import utilities.metrics
        utilities.metrics._global_assembly_collector = None

        collector = get_assembly_collector()
        assert isinstance(collector, ADSBMessageAssemblyCollector)

    def test_get_assembly_collector_returns_same_instance(self):
        """Test that get_assembly_collector returns the same instance."""
        import utilities.metrics
        utilities.metrics._global_assembly_collector = None

        collector1 = get_assembly_collector()
        collector2 = get_assembly_collector()

        assert collector1 is collector2


class TestSystemResourceSnapshot:
    """Tests for SystemResourceSnapshot dataclass."""

    def test_snapshot_creation(self):
        """Test creating a system resource snapshot."""
        snapshot = SystemResourceSnapshot(
            timestamp="2025-01-01T00:00:00+00:00",
            os_name="Linux",
            os_version="5.10.0",
            cpu_percent=25.5,
            memory_percent=45.0,
            memory_used_mb=1024.5,
            memory_available_mb=2048.0,
        )
        assert snapshot.os_name == "Linux"
        assert snapshot.cpu_percent == 25.5
        assert snapshot.memory_percent == 45.0

    def test_snapshot_to_dict(self):
        """Test converting snapshot to dictionary."""
        from dataclasses import asdict
        snapshot = SystemResourceSnapshot(
            timestamp="2025-01-01T00:00:00+00:00",
            os_name="Windows",
            os_version="10",
            cpu_percent=15.0,
            memory_percent=60.0,
            memory_used_mb=2048.0,
            memory_available_mb=2048.0,
        )
        snap_dict = asdict(snapshot)
        assert snap_dict["os_name"] == "Windows"
        assert snap_dict["memory_used_mb"] == 2048.0


class TestSystemResourceCollector:
    """Tests for SystemResourceCollector."""

    def test_collector_initialization(self):
        """Test collector can be initialized."""
        collector = SystemResourceCollector()
        assert collector.metrics_history == []
        assert collector._os_info[0] is not None  # OS name

    def test_collect_metrics(self):
        """Test collecting system resource metrics."""
        collector = SystemResourceCollector()
        snapshot = collector.collect()
        assert isinstance(snapshot, SystemResourceSnapshot)
        assert snapshot.cpu_percent >= 0
        assert snapshot.memory_percent >= 0
        assert len(collector.metrics_history) == 1

    def test_collect_multiple_times(self):
        """Test collecting metrics multiple times."""
        collector = SystemResourceCollector()
        for _ in range(3):
            collector.collect()
        assert len(collector.metrics_history) == 3

    def test_get_history(self):
        """Test retrieving metrics history."""
        collector = SystemResourceCollector()
        collector.collect()
        collector.collect()
        history = collector.get_history()
        assert len(history) == 2
        assert isinstance(history[0], SystemResourceSnapshot)

    def test_get_latest(self):
        """Test retrieving latest snapshot."""
        collector = SystemResourceCollector()
        collector.collect()
        snapshot2 = collector.collect()
        latest = collector.get_latest()
        assert latest is snapshot2

    def test_get_latest_empty(self):
        """Test getting latest when history is empty."""
        collector = SystemResourceCollector()
        assert collector.get_latest() is None

    def test_get_statistics(self):
        """Test getting aggregate statistics."""
        collector = SystemResourceCollector()
        with patch("psutil.cpu_percent", return_value=20.0):
            with patch("psutil.virtual_memory") as mock_mem:
                mock_mem.return_value = MagicMock(
                    percent=50.0, used=1024*1024*512, available=1024*1024*1024
                )
                for _ in range(3):
                    collector.collect()

        stats = collector.get_statistics()
        assert stats["count"] == 3
        assert stats["cpu_avg_percent"] > 0
        assert stats["memory_avg_percent"] > 0
        assert "os_name" in stats

    def test_get_statistics_empty(self):
        """Test getting statistics when empty."""
        collector = SystemResourceCollector()
        stats = collector.get_statistics()
        assert stats["count"] == 0
        assert stats["cpu_avg_percent"] is None
        assert stats["memory_avg_percent"] is None

    def test_export_to_json_string(self):
        """Test exporting metrics as JSON string."""
        collector = SystemResourceCollector()
        collector.collect()
        json_str = collector.export_to_json()
        data = json.loads(json_str)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["os_name"] is not None

    def test_export_to_json_file(self):
        """Test exporting metrics to a file."""
        collector = SystemResourceCollector()
        collector.collect()
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "metrics.json"
            collector.export_to_json(str(file_path))
            assert file_path.exists()
            with open(file_path) as f:
                data = json.load(f)
            assert len(data) == 1
            assert "os_name" in data[0]

    def test_clear_history(self):
        """Test clearing metrics history."""
        collector = SystemResourceCollector()
        collector.collect()
        collector.collect()
        assert len(collector.metrics_history) == 2
        collector.clear_history()
        assert len(collector.metrics_history) == 0

    def test_os_info_retrieval(self):
        """Test that OS info is properly retrieved."""
        collector = SystemResourceCollector()
        os_name, os_version = collector._os_info
        assert os_name in ["Linux", "Windows", "Darwin"]
        assert isinstance(os_version, str)


class TestGlobalSystemResourceCollector:
    """Tests for global system resource collector factory function."""

    def test_get_system_resource_collector_creates_instance(self):
        """Test that get_system_resource_collector creates an instance."""
        import utilities.metrics
        utilities.metrics._global_system_resource_collector = None

        collector = get_system_resource_collector()
        assert isinstance(collector, SystemResourceCollector)

    def test_get_system_resource_collector_returns_same_instance(self):
        """Test that get_system_resource_collector returns the same instance."""
        import utilities.metrics
        utilities.metrics._global_system_resource_collector = None

        collector1 = get_system_resource_collector()
        collector2 = get_system_resource_collector()

        assert collector1 is collector2

