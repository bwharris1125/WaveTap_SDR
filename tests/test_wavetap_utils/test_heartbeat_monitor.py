"""Tests for heartbeat monitor."""

import json
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from wavetap_utils.heartbeat_monitor import (
    ComponentHeartbeat,
    HeartbeatEvent,
    HeartbeatMonitor,
    get_heartbeat_monitor,
)


@pytest.fixture
def monitor():
    """Create a fresh HeartbeatMonitor instance for each test."""
    monitor = HeartbeatMonitor()
    yield monitor
    # Cleanup: ensure monitoring is stopped
    if monitor._monitoring_thread is not None:
        monitor.stop_monitoring()
        time.sleep(0.1)  # Give thread time to cleanup


class TestComponentHeartbeat:
    """Tests for ComponentHeartbeat dataclass."""

    def test_heartbeat_creation(self):
        """Test creating a component heartbeat."""
        hb = ComponentHeartbeat(
            component_name="test_component",
            last_heartbeat=1234567890.0,
            status="healthy",
            consecutive_failures=0,
            metadata={"key": "value"},
        )

        assert hb.component_name == "test_component"
        assert hb.last_heartbeat == 1234567890.0
        assert hb.status == "healthy"
        assert hb.consecutive_failures == 0
        assert hb.metadata == {"key": "value"}


class TestHeartbeatEvent:
    """Tests for HeartbeatEvent dataclass."""

    def test_event_creation(self):
        """Test creating a heartbeat event."""
        event = HeartbeatEvent(
            timestamp=1234567890.0,
            component_name="test",
            status="healthy",
            metadata={"test": True},
        )

        assert event.timestamp == 1234567890.0
        assert event.component_name == "test"
        assert event.status == "healthy"
        assert event.metadata == {"test": True}


class TestHeartbeatMonitor:
    """Tests for HeartbeatMonitor class."""

    def test_monitor_initialization(self):
        """Test heartbeat monitor initialization."""
        monitor = HeartbeatMonitor(heartbeat_interval=5.0, timeout=15.0)

        assert monitor.heartbeat_interval == 5.0
        assert monitor.timeout == 15.0
        assert len(monitor.components) == 0
        assert len(monitor.heartbeat_history) == 0
        assert monitor._history_limit == 10000

    def test_register_component(self):
        """Test registering a component."""
        monitor = HeartbeatMonitor()
        monitor.register_component("test_component")

        assert "test_component" in monitor.components
        assert monitor.components["test_component"].component_name == "test_component"
        assert monitor.components["test_component"].status == "unknown"
        assert monitor.components["test_component"].last_heartbeat == 0

    def test_record_heartbeat_new_component(self):
        """Test recording heartbeat for new component."""
        monitor = HeartbeatMonitor()
        monitor.record_heartbeat("test_component", status="healthy", metadata={"count": 42})

        assert "test_component" in monitor.components
        hb = monitor.components["test_component"]
        assert hb.status == "healthy"
        assert hb.metadata == {"count": 42}
        assert hb.consecutive_failures == 0
        assert hb.last_heartbeat > 0

    def test_record_heartbeat_existing_component(self):
        """Test recording heartbeat for existing component."""
        monitor = HeartbeatMonitor()
        monitor.register_component("test_component")

        first_time = time.time()
        monitor.record_heartbeat("test_component", status="healthy")
        time.sleep(0.01)
        monitor.record_heartbeat("test_component", status="degraded")

        hb = monitor.components["test_component"]
        assert hb.status == "degraded"
        assert hb.last_heartbeat > first_time
        assert hb.consecutive_failures == 1

    def test_record_heartbeat_tracks_history(self):
        """Test that heartbeats are recorded in history."""
        monitor = HeartbeatMonitor()
        monitor.record_heartbeat("comp1", "healthy")
        monitor.record_heartbeat("comp2", "degraded")

        assert len(monitor.heartbeat_history) == 2
        assert monitor.heartbeat_history[0].component_name == "comp1"
        assert monitor.heartbeat_history[1].component_name == "comp2"

    def test_heartbeat_history_limit(self):
        """Test that heartbeat history respects limit."""
        monitor = HeartbeatMonitor()
        monitor._history_limit = 5

        # Record more than limit
        for i in range(10):
            monitor.record_heartbeat(f"comp{i}", "healthy")

        assert len(monitor.heartbeat_history) == 5  # Only last 5

    def test_record_heartbeat_new_component(self, monitor):
        """Test recording heartbeat for new component."""
        monitor.record_heartbeat("test_component", status="healthy", metadata={"count": 42})

        assert "test_component" in monitor.components
        hb = monitor.components["test_component"]
        assert hb.status == "healthy"
        assert hb.metadata == {"count": 42}
        assert hb.consecutive_failures == 0
        assert hb.last_heartbeat > 0

    def test_record_heartbeat_existing_component(self, monitor):
        """Test recording heartbeat for existing component."""
        monitor.register_component("test_component")

        first_time = time.time()
        monitor.record_heartbeat("test_component", status="healthy")
        time.sleep(0.01)
        monitor.record_heartbeat("test_component", status="degraded")

        hb = monitor.components["test_component"]
        assert hb.status == "degraded"
        assert hb.last_heartbeat > first_time
        assert hb.consecutive_failures == 1

    def test_record_heartbeat_tracks_history(self, monitor):
        """Test that heartbeats are recorded in history."""
        monitor.record_heartbeat("comp1", "healthy")
        monitor.record_heartbeat("comp2", "degraded")

        assert len(monitor.heartbeat_history) == 2
        assert monitor.heartbeat_history[0].component_name == "comp1"
        assert monitor.heartbeat_history[1].component_name == "comp2"

    def test_heartbeat_history_limit(self, monitor):
        """Test that heartbeat history respects limit."""
        monitor._history_limit = 5

        # Record more than limit
        for i in range(10):
            monitor.record_heartbeat(f"comp{i}", "healthy")

        assert len(monitor.heartbeat_history) == 5  # Only last 5

    def test_consecutive_failures_increment(self, monitor):
        """Test consecutive failures increment on non-healthy status."""
        monitor.record_heartbeat("test", "degraded")
        assert monitor.components["test"].consecutive_failures == 1

        monitor.record_heartbeat("test", "critical")
        assert monitor.components["test"].consecutive_failures == 2

    def test_consecutive_failures_reset(self, monitor):
        """Test consecutive failures reset on healthy status."""
        monitor.record_heartbeat("test", "degraded")
        monitor.record_heartbeat("test", "degraded")
        assert monitor.components["test"].consecutive_failures == 2

        monitor.record_heartbeat("test", "healthy")
        assert monitor.components["test"].consecutive_failures == 0

    def test_check_health_recent_heartbeat(self, monitor):
        """Test health check with recent heartbeat."""
        monitor.timeout = 10.0
        monitor.record_heartbeat("test", "healthy")

        health = monitor.check_health()

        assert "test" in health
        assert health["test"]["status"] == "healthy"
        assert health["test"]["last_heartbeat_age"] < 1.0

    def test_check_health_timeout(self, monitor):
        """Test health check marks component critical on timeout."""
        monitor.timeout = 0.1
        monitor.register_component("test")
        monitor.components["test"].last_heartbeat = time.time() - 1.0  # Old
        monitor.components["test"].status = "healthy"

        health = monitor.check_health()

        assert health["test"]["status"] == "critical"
        assert health["test"]["last_heartbeat_age"] > 0.1

    def test_get_system_health_all_healthy(self, monitor):
        """Test system health when all components healthy."""
        monitor.record_heartbeat("comp1", "healthy")
        monitor.record_heartbeat("comp2", "healthy")

        system_health = monitor.get_system_health()
        assert system_health == "healthy"

    def test_get_system_health_one_degraded(self, monitor):
        """Test system health when one component degraded."""
        monitor.record_heartbeat("comp1", "healthy")
        monitor.record_heartbeat("comp2", "degraded")

        system_health = monitor.get_system_health()
        assert system_health == "degraded"

    def test_get_system_health_one_critical(self, monitor):
        """Test system health when one component critical."""
        monitor.record_heartbeat("comp1", "healthy")
        monitor.record_heartbeat("comp2", "critical")

        system_health = monitor.get_system_health()
        assert system_health == "critical"

    def test_get_system_health_no_components(self, monitor):
        """Test system health with no components."""
        system_health = monitor.get_system_health()
        assert system_health == "unknown"

    def test_start_stop_monitoring(self, monitor):
        """Test starting and stopping background monitoring."""
        monitor.heartbeat_interval = 0.05

        assert monitor._monitoring_thread is None

        monitor.start_monitoring()
        assert monitor._monitoring_thread is not None
        assert monitor._monitoring_thread.is_alive()

        time.sleep(0.1)  # Let it run briefly

        monitor.stop_monitoring()
        time.sleep(0.05)  # Give thread time to finish
        assert monitor._monitoring_thread is None

    def test_monitoring_callback(self, monitor):
        """Test monitoring with callback function."""
        monitor.heartbeat_interval = 0.05
        monitor.register_component("test")

        callback_data = []

        def callback(health_report):
            callback_data.append(health_report)

        monitor.start_monitoring(callback_fn=callback)
        time.sleep(0.12)  # Let it run for 2-3 intervals
        monitor.stop_monitoring()
        time.sleep(0.05)  # Give thread time to finish

        assert len(callback_data) > 0
        assert "test" in callback_data[0]

    def test_export_history(self, monitor, tmp_path):
        """Test exporting heartbeat history to JSON."""
        monitor.record_heartbeat("comp1", "healthy", {"count": 1})
        monitor.record_heartbeat("comp2", "degraded", {"count": 2})

        output_file = tmp_path / "heartbeat_history.json"
        exported_path = monitor.export_history(str(output_file))

        assert Path(exported_path).exists()

        with open(exported_path) as f:
            data = json.load(f)

        assert "export_timestamp" in data
        assert "heartbeat_interval" in data
        assert "components" in data
        assert "history" in data
        assert len(data["history"]) == 2

    def test_get_component_uptime(self, monitor):
        """Test calculating component uptime."""
        # Record some heartbeats
        monitor.record_heartbeat("test", "healthy")
        monitor.record_heartbeat("test", "healthy")
        monitor.record_heartbeat("test", "degraded")
        monitor.record_heartbeat("test", "healthy")

        uptime = monitor.get_component_uptime("test")
        assert uptime == 75.0  # 3 healthy out of 4 = 75%

    def test_get_component_uptime_no_history(self, monitor):
        """Test uptime for component with no history."""
        uptime = monitor.get_component_uptime("nonexistent")
        assert uptime is None

    def test_get_failure_count(self, monitor):
        """Test counting failures in time window."""
        # Record some failures
        monitor.record_heartbeat("test", "degraded")
        time.sleep(0.01)
        monitor.record_heartbeat("test", "critical")
        time.sleep(0.01)
        monitor.record_heartbeat("test", "healthy")

        failures = monitor.get_failure_count("test", time_window=1.0)
        assert failures == 2  # 2 non-healthy in window

    def test_get_failure_count_outside_window(self, monitor):
        """Test failure count outside time window.\"\"\"

        # Record old failure
        event = HeartbeatEvent(
            timestamp=time.time() - 100,
            component_name="test",
            status="critical",
            metadata={}
        )
        monitor.heartbeat_history.append(event)

        failures = monitor.get_failure_count("test", time_window=10.0)
        assert failures == 0  # Outside window


class TestGetHeartbeatMonitor:
    """Tests for get_heartbeat_monitor function."""

    def test_get_heartbeat_monitor_singleton(self):
        """Test that get_heartbeat_monitor returns singleton."""
        # Clear global instance
        import wavetap_utils.heartbeat_monitor as hm_module
        hm_module._global_heartbeat_monitor = None

        monitor1 = get_heartbeat_monitor()
        monitor2 = get_heartbeat_monitor()

        assert monitor1 is monitor2

    def test_get_heartbeat_monitor_with_params(self):
        """Test get_heartbeat_monitor with custom parameters."""
        import wavetap_utils.heartbeat_monitor as hm_module
        hm_module._global_heartbeat_monitor = None

        monitor = get_heartbeat_monitor(heartbeat_interval=5.0, timeout=20.0)

        assert monitor.heartbeat_interval == 5.0
        assert monitor.timeout == 20.0
