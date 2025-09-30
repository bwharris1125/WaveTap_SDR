"""
Arbiter Framework for SDR Functionality Switching

This module provides a future-proof interface for managing access to SDR hardware and switching between different SDR use cases (e.g., ADS-B, VHF Radio, FM Radio, etc.).
"""

from typing import Dict, Optional, Any

class SDRModule:
    """
    Abstract base class for SDR modules (ADS-B, VHF, FM, etc.).
    """
    def start(self):
        raise NotImplementedError
    def stop(self):
        raise NotImplementedError
    def get_status(self) -> Dict[str, Any]:
        raise NotImplementedError

class Arbiter:
    """
    Arbiter manages SDR resource access and module switching.
    """
    def __init__(self):
        self.modules: Dict[str, SDRModule] = {}
        self.active_module: Optional[str] = None

    def register_module(self, name: str, module: SDRModule):
        self.modules[name] = module

    def switch_to(self, name: str):
        if self.active_module:
            self.modules[self.active_module].stop()
        if name in self.modules:
            self.modules[name].start()
            self.active_module = name
        else:
            raise ValueError(f"Module '{name}' not registered.")

    def get_active_status(self) -> Optional[Dict[str, Any]]:
        if self.active_module:
            return self.modules[self.active_module].get_status()
        return None

    def stop_all(self):
        for module in self.modules.values():
            module.stop()
        self.active_module = None

# Example usage (future):
# arbiter = Arbiter()
# arbiter.register_module('adsb', ADSBModule())
# arbiter.register_module('vhf', VHFModule())
# arbiter.switch_to('adsb')
# status = arbiter.get_active_status()
