#!/usr/bin/env python3

"""
Health check interface and implementations for WaveTap components.

Provides a standardized way for each component to report its health status
for monitoring, alerting, and reliability analysis.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
import time


class HealthStatus(str, Enum):
    """Health status levels for components."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """Result of a health check operation."""
    status: HealthStatus
    timestamp: float
    component_name: str
    message: str = ""
    checks: Dict[str, bool] = field(default_factory=dict)
    metrics: Dict[str, float] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "status": self.status.value,
            "timestamp": self.timestamp,
            "component_name": self.component_name,
            "message": self.message,
            "checks": self.checks,
            "metrics": self.metrics,
            "errors": self.errors,
        }


class HealthCheck(ABC):
    """Abstract base class for component health checks."""

    def __init__(self, component_name: str):
        self.component_name = component_name
        self._last_check_time = 0
        self._last_result: Optional[HealthCheckResult] = None

    @abstractmethod
    def check(self) -> HealthCheckResult:
        """
        Perform health check and return result.
        
        Returns:
            HealthCheckResult with current health status
        """
        pass

    def get_cached_result(self, max_age_seconds: float = 5.0) -> Optional[HealthCheckResult]:
        """
        Get cached result if recent enough.
        
        Args:
            max_age_seconds: Maximum age of cached result in seconds
            
        Returns:
            Cached result if available and recent, None otherwise
        """
        if self._last_result is None:
            return None
        
        age = time.time() - self._last_check_time
        if age <= max_age_seconds:
            return self._last_result
        
        return None


class PublisherHealthCheck(HealthCheck):
    """Health check for ADS-B Publisher component."""

    def __init__(self, publisher):
        """
        Initialize publisher health check.
        
        Args:
            publisher: Reference to ADSBPublisher instance
        """
        super().__init__("adsb_publisher")
        self.publisher = publisher

    def check(self) -> HealthCheckResult:
        """Check publisher health."""
        now = time.time()
        self._last_check_time = now
        
        checks = {}
        metrics = {}
        errors = []

        # Check if client thread is alive
        client_alive = (
            self.publisher._client_thread is not None and 
            self.publisher._client_thread.is_alive()
        )
        checks["client_thread_alive"] = client_alive
        if not client_alive:
            errors.append("Client thread not running")

        # Check for recent messages
        last_update_times = [
            entry.get("last_update", 0) 
            for entry in self.publisher.src_client.aircraft_data.values()
        ]
        last_message = max(last_update_times) if last_update_times else 0
        message_age = now - last_message if last_message else float('inf')
        
        checks["recent_messages"] = message_age < 60.0
        metrics["last_message_age_seconds"] = message_age
        
        if message_age >= 60.0 and message_age != float('inf'):
            errors.append(f"No messages received in {message_age:.1f} seconds")

        # Count connected clients
        connected_clients = len(self.publisher.clients)
        checks["has_clients"] = connected_clients > 0
        metrics["connected_clients"] = connected_clients

        # Count tracked aircraft
        aircraft_count = len(self.publisher.src_client.aircraft_data)
        metrics["aircraft_tracked"] = aircraft_count

        # Determine overall status
        if not client_alive or (message_age > 120 and message_age != float('inf')):
            status = HealthStatus.CRITICAL
            message = "Publisher critical: " + "; ".join(errors)
        elif not checks["recent_messages"] or not checks["has_clients"]:
            status = HealthStatus.DEGRADED
            message = "Publisher degraded: " + "; ".join(errors)
        else:
            status = HealthStatus.HEALTHY
            message = f"Publisher healthy: {aircraft_count} aircraft, {connected_clients} clients"

        self._last_result = HealthCheckResult(
            status=status,
            timestamp=now,
            component_name=self.component_name,
            message=message,
            checks=checks,
            metrics=metrics,
            errors=errors,
        )
        
        return self._last_result


class SubscriberHealthCheck(HealthCheck):
    """Health check for ADS-B Subscriber component."""

    def __init__(self, subscriber):
        """
        Initialize subscriber health check.
        
        Args:
            subscriber: Reference to ADSBSubscriber instance
        """
        super().__init__("adsb_subscriber")
        self.subscriber = subscriber

    def check(self) -> HealthCheckResult:
        """Check subscriber health."""
        now = time.time()
        self._last_check_time = now
        
        checks = {}
        metrics = {}
        errors = []

        # Check WebSocket connection state (if available)
        connection_state = getattr(self.subscriber, '_connection_state', 'unknown')
        checks["connected"] = connection_state == "connected"
        if connection_state != "connected":
            errors.append(f"Connection state: {connection_state}")

        # Check for recent messages
        last_message_time = getattr(self.subscriber, '_last_message_time', 0)
        message_age = now - last_message_time if last_message_time else float('inf')
        
        checks["recent_messages"] = message_age < 60.0
        metrics["last_message_age_seconds"] = message_age
        
        if message_age >= 60.0 and message_age != float('inf'):
            errors.append(f"No messages in {message_age:.1f} seconds")

        # Check database worker
        db_alive = (
            self.subscriber.db_worker is not None and 
            self.subscriber.db_worker.is_alive()
        )
        checks["db_worker_alive"] = db_alive
        if not db_alive:
            errors.append("Database worker not running")

        # Check database queue depth
        queue_size = self.subscriber.db_worker.q.qsize() if self.subscriber.db_worker else 0
        checks["queue_healthy"] = queue_size < 1000
        metrics["db_queue_depth"] = queue_size
        
        if queue_size >= 1000:
            errors.append(f"Database queue backed up: {queue_size} items")

        # Count cached aircraft and sessions
        aircraft_count = len(self.subscriber.aircraft_data)
        session_count = len(self.subscriber.active_sessions)
        metrics["aircraft_cached"] = aircraft_count
        metrics["active_sessions"] = session_count

        # Determine overall status
        if not db_alive or (message_age > 120 and message_age != float('inf')):
            status = HealthStatus.CRITICAL
            message = "Subscriber critical: " + "; ".join(errors)
        elif not checks["connected"] or not checks["recent_messages"] or not checks["queue_healthy"]:
            status = HealthStatus.DEGRADED
            message = "Subscriber degraded: " + "; ".join(errors)
        else:
            status = HealthStatus.HEALTHY
            message = f"Subscriber healthy: {aircraft_count} aircraft, {session_count} sessions"

        self._last_result = HealthCheckResult(
            status=status,
            timestamp=now,
            component_name=self.component_name,
            message=message,
            checks=checks,
            metrics=metrics,
            errors=errors,
        )
        
        return self._last_result


class DatabaseHealthCheck(HealthCheck):
    """Health check for database operations."""

    def __init__(self, db_worker):
        """
        Initialize database health check.
        
        Args:
            db_worker: Reference to DBWorker instance
        """
        super().__init__("database")
        self.db_worker = db_worker

    def check(self) -> HealthCheckResult:
        """Check database health."""
        now = time.time()
        self._last_check_time = now
        
        checks = {}
        metrics = {}
        errors = []

        # Check if worker thread is alive
        worker_alive = self.db_worker.is_alive()
        checks["worker_alive"] = worker_alive
        if not worker_alive:
            errors.append("Database worker thread not running")

        # Check queue depth
        queue_size = self.db_worker.q.qsize()
        checks["queue_healthy"] = queue_size < 1000
        checks["queue_critical"] = queue_size < 5000
        metrics["queue_depth"] = queue_size
        
        if queue_size >= 5000:
            errors.append(f"Critical queue backup: {queue_size} items")
        elif queue_size >= 1000:
            errors.append(f"Queue backup: {queue_size} items")

        # Check database file (if not in-memory)
        if self.db_worker.db_path != ":memory:":
            import os
            db_exists = os.path.exists(self.db_worker.db_path)
            checks["db_file_exists"] = db_exists
            if not db_exists:
                errors.append("Database file not found")
            
            # Check disk space
            try:
                import shutil
                disk_usage = shutil.disk_usage(os.path.dirname(self.db_worker.db_path) or '.')
                free_gb = disk_usage.free / (1024**3)
                checks["disk_space_available"] = free_gb > 1.0
                metrics["disk_free_gb"] = free_gb
                
                if free_gb < 0.5:
                    errors.append(f"Critical: Low disk space ({free_gb:.2f} GB)")
                elif free_gb < 1.0:
                    errors.append(f"Warning: Low disk space ({free_gb:.2f} GB)")
            except Exception as e:
                errors.append(f"Could not check disk space: {e}")

        # Determine overall status
        if not worker_alive or not checks.get("queue_critical", True):
            status = HealthStatus.CRITICAL
            message = "Database critical: " + "; ".join(errors)
        elif not checks["queue_healthy"] or not checks.get("disk_space_available", True):
            status = HealthStatus.DEGRADED
            message = "Database degraded: " + "; ".join(errors)
        else:
            status = HealthStatus.HEALTHY
            message = f"Database healthy: {queue_size} items in queue"

        self._last_result = HealthCheckResult(
            status=status,
            timestamp=now,
            component_name=self.component_name,
            message=message,
            checks=checks,
            metrics=metrics,
            errors=errors,
        )
        
        return self._last_result


class SystemHealthCheck(HealthCheck):
    """Aggregate health check for entire system."""

    def __init__(self, component_checks: List[HealthCheck]):
        """
        Initialize system health check.
        
        Args:
            component_checks: List of individual component health checks
        """
        super().__init__("system")
        self.component_checks = component_checks

    def check(self) -> HealthCheckResult:
        """Check overall system health."""
        now = time.time()
        self._last_check_time = now
        
        checks = {}
        metrics = {}
        errors = []

        # Check all components
        component_results = []
        for component_check in self.component_checks:
            result = component_check.check()
            component_results.append(result)
            checks[result.component_name] = result.status == HealthStatus.HEALTHY
            
            if result.status == HealthStatus.CRITICAL:
                errors.append(f"{result.component_name}: CRITICAL")
            elif result.status == HealthStatus.DEGRADED:
                errors.append(f"{result.component_name}: DEGRADED")

        # Count component statuses
        critical_count = sum(1 for r in component_results if r.status == HealthStatus.CRITICAL)
        degraded_count = sum(1 for r in component_results if r.status == HealthStatus.DEGRADED)
        healthy_count = sum(1 for r in component_results if r.status == HealthStatus.HEALTHY)
        
        metrics["total_components"] = len(component_results)
        metrics["critical_components"] = critical_count
        metrics["degraded_components"] = degraded_count
        metrics["healthy_components"] = healthy_count

        # Determine overall status
        if critical_count > 0:
            status = HealthStatus.CRITICAL
            message = f"System critical: {critical_count} critical components"
        elif degraded_count > 0:
            status = HealthStatus.DEGRADED
            message = f"System degraded: {degraded_count} degraded components"
        elif healthy_count == len(component_results):
            status = HealthStatus.HEALTHY
            message = "All systems operational"
        else:
            status = HealthStatus.UNKNOWN
            message = "System status unknown"

        self._last_result = HealthCheckResult(
            status=status,
            timestamp=now,
            component_name=self.component_name,
            message=message,
            checks=checks,
            metrics=metrics,
            errors=errors,
        )
        
        return self._last_result