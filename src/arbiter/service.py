"""Flask wrapper that exposes the WaveTap arbiter controller as a microservice."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Dict, Optional

from flask import Flask, jsonify, request

from .arbiter_controller import Arbiter, SDRModule


class ManagedModule(SDRModule):
    """Simple in-memory module representation used for orchestration tests."""

    def __init__(self, name: str, description: str | None = None):
        self.name = name
        self.description = description
        self._active = False
        self._activated_at: Optional[datetime] = None

    def start(self):
        self._active = True
        self._activated_at = datetime.now(tz=UTC)

    def stop(self):
        self._active = False

    def get_status(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "active": self._active,
            "activated_at": self._activated_at.isoformat() if self._activated_at else None,
        }


app = Flask(__name__)


_arbiter = Arbiter()
_lock = threading.Lock()


@app.get("/health")
def health() -> tuple[Dict[str, str], int]:
    return {"status": "ok"}, 200


@app.get("/modules")
def list_modules():
    with _lock:
        payload = {name: module.get_status() for name, module in _arbiter.modules.items()}
    return jsonify(payload), 200


@app.post("/modules/stop-active")
def stop_active_module():
    with _lock:
        current = _arbiter.active_module
        if current:
            _arbiter.stop_all()
    return jsonify({"stopped": current}), 202


@app.post("/modules/<string:name>")
def register_module(name: str):
    data = request.get_json(silent=True) or {}
    description = data.get("description")
    with _lock:
        if name in _arbiter.modules:
            return jsonify({"error": f"Module '{name}' already registered"}), 409
        module = ManagedModule(name, description=description)
        _arbiter.register_module(name, module)
        status = module.get_status()
    return jsonify(status), 201


@app.delete("/modules/<string:name>")
def delete_module(name: str):
    with _lock:
        if name not in _arbiter.modules:
            return jsonify({"error": f"Module '{name}' not registered"}), 404
        module = _arbiter.modules.pop(name)
        if _arbiter.active_module == name:
            module.stop()
            _arbiter.active_module = None
    return ("", 204)


@app.post("/modules/<string:name>/activate")
def activate_module(name: str):
    with _lock:
        if name not in _arbiter.modules:
            return jsonify({"error": f"Module '{name}' not registered"}), 404
        _arbiter.switch_to(name)
        status = _arbiter.get_active_status()
    return jsonify({"active_module": name, "status": status}), 200


@app.get("/status")
def get_status():
    with _lock:
        payload = {
            "active": _arbiter.active_module,
            "status": _arbiter.get_active_status(),
            "registered": list(_arbiter.modules.keys()),
        }
    return jsonify(payload), 200


def _reset_for_testing():  # pragma: no cover - used in unit tests only
    with _lock:
        _arbiter.stop_all()
        _arbiter.modules.clear()
