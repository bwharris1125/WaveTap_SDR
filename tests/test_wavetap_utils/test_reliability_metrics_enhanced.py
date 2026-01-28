"""Tests for enhanced reliability metrics (Availability, DataQuality, Performance)."""

import json
import time
from pathlib import Path

import pytest

from wavetap_utils.reliability_metrics import (
    AvailabilityMetrics,
    AvailabilityTracker,
    DataQualityMetrics,
    DataQualityTracker,
    OutageEvent,
    PerformanceMetrics,
    PerformanceTracker,
)


class TestOutageEvent:
    """Tests for OutageEvent dataclass."""

    def test_outage_creation(self):
        """Test creating an outage event."""
        outage = OutageEvent(
            start_time=1234567890.0,
            end_time=1234567900.0,
            component="test_component",
            reason="Network failure",
        )

        assert outage.start_time == 1234567890.0
        assert outage.end_time == 1234567900.0
        assert outage.component == "test_component"
        assert outage.reason == "Network failure"

    def test_outage_duration(self):
        """Test outage duration calculation."""
        outage = OutageEvent(
            start_time=100.0,
            end_time=150.0,
            component="test",
        )

        assert outage.duration == 50.0

    def test_outage_duration_ongoing(self):
        """Test duration for ongoing outage."""
        outage = OutageEvent(
            start_time=100.0,
            end_time=None,
            component="test",
        )

        assert outage.duration is None


class TestAvailabilityMetrics:
    """Tests for AvailabilityMetrics dataclass."""

    def test_availability_percent_calculation(self):
        """Test availability percentage calculation."""
        metrics = AvailabilityMetrics(
            uptime_seconds=900.0,
            downtime_seconds=100.0,
        )

        assert metrics.availability_percent == 90.0

    def test_availability_percent_no_time(self):
        """Test availability with no time."""
        metrics = AvailabilityMetrics()
        assert metrics.availability_percent == 0.0

    def test_mtbf_single_outage(self):
        """Test MTBF with single outage."""
        metrics = AvailabilityMetrics(
            uptime_seconds=3600.0,
            total_outages=1,
        )

        assert metrics.mtbf == 3600.0

    def test_mtbf_multiple_outages(self):
        """Test MTBF with multiple outages."""
        metrics = AvailabilityMetrics(
            uptime_seconds=3600.0,
            total_outages=4,  # 3 intervals between 4 outages
        )

        assert metrics.mtbf == 1200.0  # 3600 / 3

    def test_mttr_calculation(self):
        """Test MTTR calculation."""
        outages = [
            OutageEvent(0, 10, "comp", "reason1"),  # 10s
            OutageEvent(20, 30, "comp", "reason2"),  # 10s
            OutageEvent(40, 60, "comp", "reason3"),  # 20s
        ]
        metrics = AvailabilityMetrics(
            downtime_seconds=40.0,
            outage_history=outages,
        )

        assert metrics.mttr == pytest.approx(13.333, rel=0.01)  # (10+10+20)/3

    def test_mttr_no_outages(self):
        """Test MTTR with no outages."""
        metrics = AvailabilityMetrics()
        assert metrics.mttr == 0.0


class TestAvailabilityTracker:
    """Tests for AvailabilityTracker class."""

    def test_tracker_initialization(self):
        """Test availability tracker initialization."""
        tracker = AvailabilityTracker()

        assert tracker.metrics.uptime_seconds == 0.0
        assert tracker.metrics.downtime_seconds == 0.0
        assert tracker.metrics.total_outages == 0
        assert tracker._current_outage is None

    def test_record_outage_start(self):
        """Test recording outage start."""
        tracker = AvailabilityTracker()
        tracker.record_outage_start(component="test", reason="failure")

        assert tracker._current_outage is not None
        assert tracker._current_outage.component == "test"
        assert tracker._current_outage.reason == "failure"
        assert tracker.metrics.total_outages == 1
        assert tracker._last_state == "down"

    def test_record_outage_end(self):
        """Test recording outage end."""
        tracker = AvailabilityTracker()
        tracker.record_outage_start(component="test", reason="failure")
        time.sleep(0.01)
        tracker.record_outage_end()

        assert tracker._current_outage is None
        assert tracker._last_state == "up"
        assert len(tracker.metrics.outage_history) == 1
        assert tracker.metrics.downtime_seconds > 0

    def test_record_outage_end_no_active(self):
        """Test ending outage when none active."""
        tracker = AvailabilityTracker()
        tracker.record_outage_end()  # Should not crash

        assert tracker._current_outage is None

    def test_multiple_outages(self):
        """Test recording multiple outages."""
        tracker = AvailabilityTracker()
        
        tracker.record_outage_start("comp1", "reason1")
        time.sleep(0.01)
        tracker.record_outage_end()
        
        tracker.record_outage_start("comp2", "reason2")
        time.sleep(0.01)
        tracker.record_outage_end()

        assert tracker.metrics.total_outages == 2
        assert len(tracker.metrics.outage_history) == 2

    def test_get_metrics(self):
        """Test getting metrics."""
        tracker = AvailabilityTracker()
        tracker.record_outage_start("test", "failure")
        time.sleep(0.01)
        tracker.record_outage_end()

        metrics = tracker.get_metrics()
        
        assert isinstance(metrics, AvailabilityMetrics)
        assert metrics.total_outages == 1
        assert metrics.downtime_seconds > 0

    def test_export_to_json(self, tmp_path):
        """Test exporting metrics to JSON."""
        tracker = AvailabilityTracker()
        tracker.record_outage_start("test", "failure")
        time.sleep(0.01)
        tracker.record_outage_end()

        output_file = tmp_path / "availability.json"
        exported_path = tracker.export_to_json(str(output_file))

        assert Path(exported_path).exists()
        
        with open(exported_path) as f:
            data = json.load(f)
        
        assert "timestamp" in data
        assert "uptime_seconds" in data
        assert "downtime_seconds" in data
        assert "availability_percent" in data
        assert "mtbf_seconds" in data
        assert "mttr_seconds" in data
        assert "outage_history" in data


class TestDataQualityMetrics:
    """Tests for DataQualityMetrics dataclass."""

    def test_message_success_rate(self):
        """Test message success rate calculation."""
        metrics = DataQualityMetrics(
            messages_received=100,
            messages_valid=90,
        )

        assert metrics.message_success_rate == 90.0

    def test_message_success_rate_no_messages(self):
        """Test success rate with no messages."""
        metrics = DataQualityMetrics()
        assert metrics.message_success_rate == 0.0

    def test_assembly_success_rate(self):
        """Test assembly success rate calculation."""
        metrics = DataQualityMetrics(
            assembly_completed=80,
            assembly_timeouts=20,
        )

        assert metrics.assembly_success_rate == 80.0

    def test_position_success_rate(self):
        """Test position success rate calculation."""
        metrics = DataQualityMetrics(
            position_successes=150,
            position_failures=50,
        )

        assert metrics.position_success_rate == 75.0


class TestDataQualityTracker:
    """Tests for DataQualityTracker class."""

    def test_tracker_initialization(self):
        """Test data quality tracker initialization."""
        tracker = DataQualityTracker()

        assert tracker.metrics.messages_received == 0
        assert tracker.metrics.messages_valid == 0

    def test_record_message_received(self):
        """Test recording message received."""
        tracker = DataQualityTracker()
        tracker.record_message_received()
        tracker.record_message_received()

        assert tracker.metrics.messages_received == 2

    def test_record_message_valid(self):
        """Test recording valid message."""
        tracker = DataQualityTracker()
        tracker.record_message_valid()

        assert tracker.metrics.messages_valid == 1

    def test_record_message_dropped(self):
        """Test recording dropped message."""
        tracker = DataQualityTracker()
        tracker.record_message_dropped()

        assert tracker.metrics.messages_dropped == 1

    def test_record_message_malformed(self):
        """Test recording malformed message."""
        tracker = DataQualityTracker()
        tracker.record_message_malformed()

        assert tracker.metrics.messages_malformed == 1

    def test_record_assembly_metrics(self):
        """Test recording assembly metrics."""
        tracker = DataQualityTracker()
        tracker.record_assembly_completed()
        tracker.record_assembly_completed()
        tracker.record_assembly_timeout()

        assert tracker.metrics.assembly_completed == 2
        assert tracker.metrics.assembly_timeouts == 1

    def test_record_position_metrics(self):
        """Test recording position metrics."""
        tracker = DataQualityTracker()
        tracker.record_position_success()
        tracker.record_position_success()
        tracker.record_position_failure()

        assert tracker.metrics.position_successes == 2
        assert tracker.metrics.position_failures == 1

    def test_record_stale_cpr_pair(self):
        """Test recording stale CPR pair."""
        tracker = DataQualityTracker()
        tracker.record_stale_cpr_pair()

        assert tracker.metrics.stale_cpr_pairs == 1

    def test_export_to_json(self, tmp_path):
        """Test exporting metrics to JSON."""
        tracker = DataQualityTracker()
        tracker.record_message_received()
        tracker.record_message_valid()
        tracker.record_assembly_completed()

        output_file = tmp_path / "data_quality.json"
        exported_path = tracker.export_to_json(str(output_file))

        assert Path(exported_path).exists()
        
        with open(exported_path) as f:
            data = json.load(f)
        
        assert "messages_received" in data
        assert "message_success_rate_percent" in data
        assert "assembly_success_rate_percent" in data


class TestPerformanceMetrics:
    """Tests for PerformanceMetrics dataclass."""

    def test_add_message_latency(self):
        """Test adding message latency."""
        metrics = PerformanceMetrics()
        metrics.add_message_latency(10.5)
        metrics.add_message_latency(20.0)

        assert len(metrics.message_latencies_ms) == 2

    def test_latency_deque_limit(self):
        """Test that latency deque respects maxlen."""
        metrics = PerformanceMetrics()
        
        # Add more than 1000
        for i in range(1500):
            metrics.add_message_latency(i)

        assert len(metrics.message_latencies_ms) == 1000

    def test_get_latency_stats_empty(self):
        """Test latency stats with no data."""
        metrics = PerformanceMetrics()
        stats = metrics.get_latency_stats(metrics.message_latencies_ms)

        assert stats["count"] == 0
        assert stats["min"] == 0.0
        assert stats["max"] == 0.0

    def test_get_latency_stats(self):
        """Test latency statistics calculation."""
        metrics = PerformanceMetrics()
        for val in [10, 20, 30, 40, 50]:
            metrics.add_message_latency(val)

        stats = metrics.message_latency_stats

        assert stats["count"] == 5
        assert stats["min"] == 10
        assert stats["max"] == 50
        assert stats["mean"] == 30.0
        assert stats["p50"] == 30

    def test_db_write_latency_stats(self):
        """Test DB write latency statistics."""
        metrics = PerformanceMetrics()
        metrics.add_db_write_latency(5.0)
        metrics.add_db_write_latency(15.0)

        stats = metrics.db_write_latency_stats

        assert stats["count"] == 2
        assert stats["min"] == 5.0
        assert stats["max"] == 15.0

    def test_assembly_time_stats(self):
        """Test assembly time statistics."""
        metrics = PerformanceMetrics()
        metrics.add_assembly_time(100.0)
        metrics.add_assembly_time(200.0)

        stats = metrics.assembly_time_stats

        assert stats["count"] == 2
        assert stats["mean"] == 150.0


class TestPerformanceTracker:
    """Tests for PerformanceTracker class."""

    def test_tracker_initialization(self):
        """Test performance tracker initialization."""
        tracker = PerformanceTracker()

        assert len(tracker.metrics.message_latencies_ms) == 0

    def test_record_message_latency(self):
        """Test recording message latency."""
        tracker = PerformanceTracker()
        tracker.record_message_latency(25.5)

        assert len(tracker.metrics.message_latencies_ms) == 1
        assert tracker.metrics.message_latencies_ms[0] == 25.5

    def test_record_db_write_latency(self):
        """Test recording DB write latency."""
        tracker = PerformanceTracker()
        tracker.record_db_write_latency(10.0)

        assert len(tracker.metrics.db_write_latencies_ms) == 1

    def test_record_assembly_time(self):
        """Test recording assembly time."""
        tracker = PerformanceTracker()
        tracker.record_assembly_time(150.0)

        assert len(tracker.metrics.assembly_times_ms) == 1

    def test_get_metrics(self):
        """Test getting metrics."""
        tracker = PerformanceTracker()
        tracker.record_message_latency(10.0)
        tracker.record_message_latency(20.0)

        metrics = tracker.get_metrics()

        assert isinstance(metrics, PerformanceMetrics)
        assert len(metrics.message_latencies_ms) == 2

    def test_export_to_json(self, tmp_path):
        """Test exporting metrics to JSON."""
        tracker = PerformanceTracker()
        tracker.record_message_latency(10.0)
        tracker.record_db_write_latency(5.0)
        tracker.record_assembly_time(100.0)

        output_file = tmp_path / "performance.json"
        exported_path = tracker.export_to_json(str(output_file))

        assert Path(exported_path).exists()
        
        with open(exported_path) as f:
            data = json.load(f)
        
        assert "timestamp" in data
        assert "message_latency" in data
        assert "db_write_latency" in data
        assert "assembly_time" in data
        assert data["message_latency"]["count"] == 1
