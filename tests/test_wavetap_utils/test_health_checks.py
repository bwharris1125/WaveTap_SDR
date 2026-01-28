"""Tests for health check implementations."""

import time
from unittest.mock import MagicMock, Mock

import pytest

from wavetap_utils.health_checks import (
    DatabaseHealthCheck,
    HealthCheck,
    HealthCheckResult,
    HealthStatus,
    PublisherHealthCheck,
    SubscriberHealthCheck,
    SystemHealthCheck,
)


class TestHealthStatus:
    """Tests for HealthStatus enum."""

    def test_health_status_values(self):
        """Test HealthStatus enum values."""
        assert HealthStatus.HEALTHY == "healthy"
        assert HealthStatus.DEGRADED == "degraded"
        assert HealthStatus.CRITICAL == "critical"
        assert HealthStatus.UNKNOWN == "unknown"


class TestHealthCheckResult:
    """Tests for HealthCheckResult dataclass."""

    def test_result_creation(self):
        """Test creating a health check result."""
        result = HealthCheckResult(
            status=HealthStatus.HEALTHY,
            timestamp=time.time(),
            component_name="test_component",
            message="All good",
            checks={"test": True},
            metrics={"count": 42.0},
            errors=[],
        )

        assert result.status == HealthStatus.HEALTHY
        assert result.component_name == "test_component"
        assert result.message == "All good"
        assert result.checks["test"] is True
        assert result.metrics["count"] == 42.0
        assert len(result.errors) == 0

    def test_result_to_dict(self):
        """Test converting result to dictionary."""
        result = HealthCheckResult(
            status=HealthStatus.DEGRADED,
            timestamp=1234567890.0,
            component_name="test",
            message="Warning",
            checks={"a": True, "b": False},
            metrics={"x": 1.0, "y": 2.0},
            errors=["Error 1"],
        )

        result_dict = result.to_dict()
        assert result_dict["status"] == "degraded"
        assert result_dict["timestamp"] == 1234567890.0
        assert result_dict["component_name"] == "test"
        assert result_dict["message"] == "Warning"
        assert result_dict["checks"] == {"a": True, "b": False}
        assert result_dict["metrics"] == {"x": 1.0, "y": 2.0}
        assert result_dict["errors"] == ["Error 1"]


class MockHealthCheck(HealthCheck):
    """Mock health check for testing abstract base class."""

    def __init__(self, component_name: str, result: HealthCheckResult):
        super().__init__(component_name)
        self._result = result

    def check(self) -> HealthCheckResult:
        self._last_check_time = time.time()
        self._last_result = self._result
        return self._result


class TestHealthCheck:
    """Tests for HealthCheck abstract base class."""

    def test_health_check_initialization(self):
        """Test health check initialization."""
        result = HealthCheckResult(
            status=HealthStatus.HEALTHY,
            timestamp=time.time(),
            component_name="test",
        )
        hc = MockHealthCheck("test", result)
        assert hc.component_name == "test"
        assert hc._last_check_time == 0
        assert hc._last_result is None

    def test_cached_result_when_fresh(self):
        """Test getting cached result when fresh."""
        result = HealthCheckResult(
            status=HealthStatus.HEALTHY,
            timestamp=time.time(),
            component_name="test",
        )
        hc = MockHealthCheck("test", result)

        # First check
        hc.check()

        # Get cached result immediately
        cached = hc.get_cached_result(max_age_seconds=5.0)
        assert cached is not None
        assert cached.status == HealthStatus.HEALTHY

    def test_cached_result_when_stale(self):
        """Test getting cached result when stale."""
        result = HealthCheckResult(
            status=HealthStatus.HEALTHY,
            timestamp=time.time(),
            component_name="test",
        )
        hc = MockHealthCheck("test", result)

        # First check
        hc.check()

        # Wait and get stale cached result
        time.sleep(0.1)
        cached = hc.get_cached_result(max_age_seconds=0.05)
        assert cached is None

    def test_cached_result_when_never_checked(self):
        """Test getting cached result when never checked."""
        result = HealthCheckResult(
            status=HealthStatus.HEALTHY,
            timestamp=time.time(),
            component_name="test",
        )
        hc = MockHealthCheck("test", result)

        cached = hc.get_cached_result()
        assert cached is None


class TestPublisherHealthCheck:
    """Tests for PublisherHealthCheck."""

    def test_healthy_publisher(self):
        """Test health check for healthy publisher."""
        # Mock publisher
        publisher = Mock()
        publisher._client_thread = Mock()
        publisher._client_thread.is_alive.return_value = True
        publisher.clients = {Mock(), Mock()}  # 2 clients

        # Mock aircraft data with recent updates
        now = time.time()
        publisher.src_client = Mock()
        publisher.src_client.aircraft_data = {
            "ABC123": {"last_update": now - 5},
            "DEF456": {"last_update": now - 10},
        }

        hc = PublisherHealthCheck(publisher)
        result = hc.check()

        assert result.status == HealthStatus.HEALTHY
        assert result.checks["client_thread_alive"] is True
        assert result.checks["recent_messages"] is True
        assert result.checks["has_clients"] is True
        assert result.metrics["connected_clients"] == 2
        assert result.metrics["aircraft_tracked"] == 2
        assert len(result.errors) == 0

    def test_degraded_publisher_no_messages(self):
        """Test degraded publisher with no recent messages."""
        publisher = Mock()
        publisher._client_thread = Mock()
        publisher._client_thread.is_alive.return_value = True
        publisher.clients = {Mock()}

        # Old message data
        old_time = time.time() - 90  # 90 seconds ago
        publisher.src_client = Mock()
        publisher.src_client.aircraft_data = {
            "ABC123": {"last_update": old_time},
        }

        hc = PublisherHealthCheck(publisher)
        result = hc.check()

        assert result.status == HealthStatus.DEGRADED
        assert result.checks["recent_messages"] is False
        assert len(result.errors) > 0

    def test_critical_publisher_thread_dead(self):
        """Test critical publisher with dead thread."""
        publisher = Mock()
        publisher._client_thread = None
        publisher.clients = set()
        publisher.src_client = Mock()
        publisher.src_client.aircraft_data = {}

        hc = PublisherHealthCheck(publisher)
        result = hc.check()

        assert result.status == HealthStatus.CRITICAL
        assert result.checks["client_thread_alive"] is False
        assert "Client thread not running" in result.errors


class TestSubscriberHealthCheck:
    """Tests for SubscriberHealthCheck."""

    def test_healthy_subscriber(self):
        """Test health check for healthy subscriber."""
        subscriber = Mock()
        subscriber._connection_state = "connected"
        subscriber._last_message_time = time.time() - 5  # 5 seconds ago
        subscriber.aircraft_data = {"ABC": {}, "DEF": {}}
        subscriber.active_sessions = {"ABC": "sess1", "DEF": "sess2"}

        subscriber.db_worker = Mock()
        subscriber.db_worker.is_alive.return_value = True
        subscriber.db_worker.q = Mock()
        subscriber.db_worker.q.qsize.return_value = 50

        hc = SubscriberHealthCheck(subscriber)
        result = hc.check()

        assert result.status == HealthStatus.HEALTHY
        assert result.checks["connected"] is True
        assert result.checks["recent_messages"] is True
        assert result.checks["db_worker_alive"] is True
        assert result.checks["queue_healthy"] is True
        assert result.metrics["aircraft_cached"] == 2
        assert result.metrics["active_sessions"] == 2

    def test_degraded_subscriber_queue_backed_up(self):
        """Test degraded subscriber with backed up queue."""
        subscriber = Mock()
        subscriber._connection_state = "connected"
        subscriber._last_message_time = time.time() - 5
        subscriber.aircraft_data = {}
        subscriber.active_sessions = {}

        subscriber.db_worker = Mock()
        subscriber.db_worker.is_alive.return_value = True
        subscriber.db_worker.q = Mock()
        subscriber.db_worker.q.qsize.return_value = 1500  # Backed up

        hc = SubscriberHealthCheck(subscriber)
        result = hc.check()

        assert result.status == HealthStatus.DEGRADED
        assert result.checks["queue_healthy"] is False
        assert "queue backed up" in result.errors[0].lower()

    def test_critical_subscriber_db_dead(self):
        """Test critical subscriber with dead database worker."""
        subscriber = Mock()
        subscriber._connection_state = "connected"
        subscriber._last_message_time = time.time()
        subscriber.aircraft_data = {}
        subscriber.active_sessions = {}

        subscriber.db_worker = None

        hc = SubscriberHealthCheck(subscriber)
        result = hc.check()

        assert result.status == HealthStatus.CRITICAL
        assert result.checks["db_worker_alive"] is False


class TestDatabaseHealthCheck:
    """Tests for DatabaseHealthCheck."""

    def test_healthy_database(self):
        """Test health check for healthy database."""
        db_worker = Mock()
        db_worker.is_alive.return_value = True
        db_worker.q = Mock()
        db_worker.q.qsize.return_value = 10
        db_worker.db_path = ":memory:"

        hc = DatabaseHealthCheck(db_worker)
        result = hc.check()

        assert result.status == HealthStatus.HEALTHY
        assert result.checks["worker_alive"] is True
        assert result.checks["queue_healthy"] is True
        assert result.metrics["queue_depth"] == 10

    def test_degraded_database_queue_warning(self):
        """Test degraded database with queue warning."""
        db_worker = Mock()
        db_worker.is_alive.return_value = True
        db_worker.q = Mock()
        db_worker.q.qsize.return_value = 1500  # Warning level
        db_worker.db_path = ":memory:"

        hc = DatabaseHealthCheck(db_worker)
        result = hc.check()

        assert result.status == HealthStatus.DEGRADED
        assert result.checks["queue_healthy"] is False
        assert result.checks["queue_critical"] is True

    def test_critical_database_queue_critical(self):
        """Test critical database with critical queue backup."""
        db_worker = Mock()
        db_worker.is_alive.return_value = True
        db_worker.q = Mock()
        db_worker.q.qsize.return_value = 6000  # Critical level
        db_worker.db_path = ":memory:"

        hc = DatabaseHealthCheck(db_worker)
        result = hc.check()

        assert result.status == HealthStatus.CRITICAL
        assert result.checks["queue_critical"] is False

    def test_database_with_file_checks(self, tmp_path):
        """Test database health check with file-based database."""
        import os

        db_file = tmp_path / "test.db"
        db_file.write_text("test")

        db_worker = Mock()
        db_worker.is_alive.return_value = True
        db_worker.q = Mock()
        db_worker.q.qsize.return_value = 10
        db_worker.db_path = str(db_file)

        hc = DatabaseHealthCheck(db_worker)
        result = hc.check()

        assert result.checks["db_file_exists"] is True
        assert "disk_free_gb" in result.metrics


class TestSystemHealthCheck:
    """Tests for SystemHealthCheck."""

    def test_system_healthy_all_components(self):
        """Test system health when all components healthy."""
        # Create mock component checks
        comp1_result = HealthCheckResult(
            status=HealthStatus.HEALTHY,
            timestamp=time.time(),
            component_name="comp1",
        )
        comp2_result = HealthCheckResult(
            status=HealthStatus.HEALTHY,
            timestamp=time.time(),
            component_name="comp2",
        )

        comp1_check = MockHealthCheck("comp1", comp1_result)
        comp2_check = MockHealthCheck("comp2", comp2_result)

        system_check = SystemHealthCheck([comp1_check, comp2_check])
        result = system_check.check()

        assert result.status == HealthStatus.HEALTHY
        assert result.message == "All systems operational"
        assert result.metrics["total_components"] == 2
        assert result.metrics["healthy_components"] == 2
        assert result.metrics["degraded_components"] == 0
        assert result.metrics["critical_components"] == 0

    def test_system_degraded_one_component(self):
        """Test system degraded when one component degraded."""
        comp1_result = HealthCheckResult(
            status=HealthStatus.HEALTHY,
            timestamp=time.time(),
            component_name="comp1",
        )
        comp2_result = HealthCheckResult(
            status=HealthStatus.DEGRADED,
            timestamp=time.time(),
            component_name="comp2",
        )

        comp1_check = MockHealthCheck("comp1", comp1_result)
        comp2_check = MockHealthCheck("comp2", comp2_result)

        system_check = SystemHealthCheck([comp1_check, comp2_check])
        result = system_check.check()

        assert result.status == HealthStatus.DEGRADED
        assert result.metrics["degraded_components"] == 1
        assert "comp2: DEGRADED" in result.errors

    def test_system_critical_one_component(self):
        """Test system critical when one component critical."""
        comp1_result = HealthCheckResult(
            status=HealthStatus.HEALTHY,
            timestamp=time.time(),
            component_name="comp1",
        )
        comp2_result = HealthCheckResult(
            status=HealthStatus.CRITICAL,
            timestamp=time.time(),
            component_name="comp2",
        )

        comp1_check = MockHealthCheck("comp1", comp1_result)
        comp2_check = MockHealthCheck("comp2", comp2_result)

        system_check = SystemHealthCheck([comp1_check, comp2_check])
        result = system_check.check()

        assert result.status == HealthStatus.CRITICAL
        assert result.metrics["critical_components"] == 1
        assert "comp2: CRITICAL" in result.errors
