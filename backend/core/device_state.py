import time
import logging
from enum import Enum
from typing import Callable, List, Optional, Dict, Any

logger = logging.getLogger("ai_voice_assistant.device_state")


class DeviceState(str, Enum):
    BOOTING = "BOOTING"
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"
    SHUTDOWN = "SHUTDOWN"


class DeviceStateManager:
    """Manages physical hardware/board status independently from Assistant conversational state."""

    def __init__(self):
        self._state: DeviceState = DeviceState.READY
        self._last_changed: float = time.time()
        self._listeners: List[Callable[[DeviceState, dict], None]] = []
        self._telemetry: Dict[str, Any] = {
            "battery_percent": 100,
            "is_charging": True,
            "wifi_connected": True,
            "cpu_temp_c": 42.0,
            "audio_input_ready": True,
            "audio_output_ready": True,
        }

    @property
    def current_state(self) -> DeviceState:
        """Get current physical device state."""
        return self._state

    @property
    def telemetry(self) -> Dict[str, Any]:
        """Get physical device telemetry stats."""
        return self._telemetry.copy()

    def register_listener(self, listener: Callable[[DeviceState, dict], None]) -> None:
        """Register a callback for device state changes."""
        self._listeners.append(listener)

    def set_device_state(self, new_state: DeviceState, details: Optional[dict] = None) -> None:
        """Update device hardware state."""
        if self._state != new_state:
            old_state = self._state
            self._state = new_state
            self._last_changed = time.time()
            logger.info(f"Device hardware state transitioned: {old_state.value} -> {new_state.value}")

            meta = details or {}
            for callback in self._listeners:
                try:
                    callback(new_state, meta)
                except Exception as e:
                    logger.error(f"Error in device state listener: {e}")

    def update_telemetry(self, updates: Dict[str, Any]) -> None:
        """Update hardware telemetry data."""
        self._telemetry.update(updates)


_device_state_manager_instance: Optional[DeviceStateManager] = None


def get_device_state_manager() -> DeviceStateManager:
    """Singleton getter for DeviceStateManager."""
    global _device_state_manager_instance
    if _device_state_manager_instance is None:
        _device_state_manager_instance = DeviceStateManager()
    return _device_state_manager_instance
