#!/usr/bin/env python3

"""System-wide heartbeat and health monitoring."""
import json
import logging
import time
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ComponentHeartbeat:
    """Heartbeat record for a component."""
    component_name: str
    last_heartbeat: float
    status: str  # "healthy", "degraded", "critical", "unknown"
    consecutive_failures: int = 0
    metadata: Dict = field(default_factory=dict)


@dataclass
class HeartbeatEvent:
    """Record of a heartbeat event for historical tracking."""
    timestamp: float
    component_name: str
    status: str
    metadata: Dict


class HeartbeatMonitor:
    """Central heartbeat monitor for all WaveTap components."""

    def __init__(self, heartbeat_interval: float = 10.0, timeout: float = 30.0):
        self.heartbeat_interval = heartbeat_interval
        self.timeout = timeout
        self.components: Dict[str, ComponentHeartbeat] = {}
        self.heartbeat_history: List[HeartbeatEvent] = []
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)
        self._monitoring_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._history_limit = 10000  # Keep last 10k heartbeat events

    def register_component(self, name: str):
        """Register a component for monitoring."""
        with self._lock:
            self.components[name] = ComponentHeartbeat(
                component_name=name,
                last_heartbeat=0,
                status="unknown"
            )
        self._logger.info(f"Registered component: {name}")

    def record_heartbeat(self, name: str, status: str = "healthy", metadata: dict = None):
        """Record a heartbeat from a component."""
        now = time.time()
        
        with self._lock:
            if name not in self.components:
                self.register_component(name)

            hb = self.components[name]
            hb.last_heartbeat = now
            hb.status = status
            hb.metadata = metadata or {}

            if status == "healthy":
                hb.consecutive_failures = 0
            else:
                hb.consecutive_failures += 1

            # Record to history
            event = HeartbeatEvent(
                timestamp=now,
                component_name=name,
                status=status,
                metadata=metadata or {}
            )
            self.heartbeat_history.append(event)
            
            # Trim history if needed
            if len(self.heartbeat_history) > self._history_limit:
                self.heartbeat_history = self.heartbeat_history[-self._history_limit:]

        self._logger.debug(f"Heartbeat recorded for {name}: {status}")

    def check_health(self) -> Dict[str, Dict]:
        """Check health of all registered components."""
        now = time.time()
        health_report = {}

        with self._lock:
            for name, hb in self.components.items():
                age = now - hb.last_heartbeat

                # Determine health based on timeout
                if age > self.timeout:
                    status = "critical"
                    if hb.status != "critical":
                        self._logger.warning(f"Component {name} timeout (age: {age:.1f}s)")
                elif hb.status == "degraded":
                    status = "degraded"
                else:
                    status = hb.status

                health_report[name] = {
                    "status": status,
                    "last_heartbeat_age": age,
                    "consecutive_failures": hb.consecutive_failures,
                    "metadata": hb.metadata,
                }

        return health_report

    def get_system_health(self) -> str:
        """Get overall system health status."""
        health = self.check_health()

        if not health:
            return "unknown"

        if any(c["status"] == "critical" for c in health.values()):
            return "critical"
        elif any(c["status"] == "degraded" for c in health.values()):
            return "degraded"
        elif all(c["status"] == "healthy" for c in health.values()):
            return "healthy"
        else:
            return "unknown"

    def start_monitoring(self, callback_fn=None):
        """
        Start background monitoring thread.
        
        Args:
            callback_fn: Optional callback function called with health report on each check
        """
        if self._monitoring_thread is not None:
            self._logger.warning("Monitoring already running")
            return

        self._stop_event.clear()
        self._monitoring_thread = threading.Thread(
            target=self._monitoring_worker,
            args=(callback_fn,),
            daemon=True,
        )
        self._monitoring_thread.start()
        self._logger.info(f"Heartbeat monitoring started (interval: {self.heartbeat_interval}s)")

    def stop_monitoring(self):
        """Stop background monitoring thread."""
        if self._monitoring_thread is None:
            return

        self._stop_event.set()
        self._monitoring_thread.join(timeout=5.0)
        self._monitoring_thread = None
        self._logger.info("Heartbeat monitoring stopped")

    def _monitoring_worker(self, callback_fn):
        """Worker thread that periodically checks component health."""
        while not self._stop_event.is_set():
            try:
                health_report = self.check_health()
                
                # Log any unhealthy components
                for name, info in health_report.items():
                    if info["status"] in ("critical", "degraded"):
                        self._logger.warning(
                            f"Component {name} is {info['status']}: "
                            f"last heartbeat {info['last_heartbeat_age']:.1f}s ago, "
                            f"{info['consecutive_failures']} consecutive failures"
                        )
                
                # Call callback if provided
                if callback_fn:
                    try:
                        callback_fn(health_report)
                    except Exception as e:
                        self._logger.error(f"Error in monitoring callback: {e}")

            except Exception as e:
                self._logger.error(f"Error in monitoring worker: {e}")

            self._stop_event.wait(self.heartbeat_interval)

    def export_history(self, file_path: Optional[str] = None) -> str:
        """
        Export heartbeat history to JSON file.
        
        Args:
            file_path: Path to export file. If None, uses default location.
            
        Returns:
            Path to exported file
        """
        if file_path is None:
            metrics_dir = Path.cwd() / "tmp" / "metrics"
            metrics_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            file_path = str(metrics_dir / f"heartbeat_history_{timestamp}.json")

        with self._lock:
            data = {
                "export_timestamp": datetime.now(UTC).isoformat(),
                "heartbeat_interval": self.heartbeat_interval,
                "timeout": self.timeout,
                "components": {
                    name: asdict(hb) 
                    for name, hb in self.components.items()
                },
                "history": [
                    {
                        "timestamp": event.timestamp,
                        "component_name": event.component_name,
                        "status": event.status,
                        "metadata": event.metadata,
                    }
                    for event in self.heartbeat_history
                ],
            }

        try:
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)
            self._logger.info(f"Heartbeat history exported to {file_path}")
        except Exception as e:
            self._logger.error(f"Failed to export heartbeat history: {e}")
            raise

        return file_path

    def get_component_uptime(self, component_name: str) -> Optional[float]:
        """
        Calculate uptime percentage for a component based on history.
        
        Args:
            component_name: Name of component
            
        Returns:
            Uptime percentage (0-100) or None if no history
        """
        with self._lock:
            component_events = [
                e for e in self.heartbeat_history 
                if e.component_name == component_name
            ]

        if not component_events:
            return None

        healthy_count = sum(1 for e in component_events if e.status == "healthy")
        return (healthy_count / len(component_events)) * 100

    def get_failure_count(self, component_name: str, time_window: float = 3600) -> int:
        """
        Count failures for a component in a time window.
        
        Args:
            component_name: Name of component
            time_window: Time window in seconds (default: 1 hour)
            
        Returns:
            Number of non-healthy heartbeats in window
        """
        now = time.time()
        cutoff = now - time_window

        with self._lock:
            failures = [
                e for e in self.heartbeat_history
                if (e.component_name == component_name and 
                    e.timestamp >= cutoff and 
                    e.status != "healthy")
            ]

        return len(failures)


# Global heartbeat monitor instance
_global_heartbeat_monitor: Optional[HeartbeatMonitor] = None


def get_heartbeat_monitor(
    heartbeat_interval: float = 10.0,
    timeout: float = 30.0
) -> HeartbeatMonitor:
    """
    Get or create the global heartbeat monitor.
    
    Args:
        heartbeat_interval: Interval between heartbeats in seconds
        timeout: Timeout before component marked critical in seconds
        
    Returns:
        The global HeartbeatMonitor instance
    """
    global _global_heartbeat_monitor

    if _global_heartbeat_monitor is None:
        _global_heartbeat_monitor = HeartbeatMonitor(
            heartbeat_interval=heartbeat_interval,
            timeout=timeout
        )

    return _global_heartbeat_monitor
