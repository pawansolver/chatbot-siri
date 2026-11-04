import pytest
from backend.core.device_state import DeviceStateManager, DeviceState, get_device_state_manager
from backend.core.state_manager import StateManager, AssistantState, get_state_manager


def test_device_state_vs_assistant_state_independence():
    """Verify physical DeviceState and conversational AssistantState remain strictly decoupled."""
    device_mgr = DeviceStateManager()
    assistant_sm = StateManager()

    # Initial states
    assert device_mgr.current_state == DeviceState.READY
    assert assistant_sm.current_state == AssistantState.IDLE

    # Transition AssistantState through conversation lifecycle
    assistant_sm.set_state(AssistantState.LISTENING)
    assistant_sm.set_state(AssistantState.THINKING)
    assert assistant_sm.current_state == AssistantState.THINKING
    # Device state MUST remain unchanged (READY)
    assert device_mgr.current_state == DeviceState.READY

    # Change DeviceState to OFFLINE (e.g. Wi-Fi disconnected on Raspberry Pi)
    device_mgr.set_device_state(DeviceState.OFFLINE)
    assert device_mgr.current_state == DeviceState.OFFLINE
    # Assistant state still tracks its own state
    assert assistant_sm.current_state == AssistantState.THINKING

    # Assistant resets to IDLE
    assistant_sm.reset_to_idle()
    assert assistant_sm.current_state == AssistantState.IDLE
    assert device_mgr.current_state == DeviceState.OFFLINE


def test_device_telemetry_updates():
    """Verify DeviceStateManager tracks hardware telemetry stats."""
    device_mgr = DeviceStateManager()
    device_mgr.update_telemetry({"battery_percent": 85, "cpu_temp_c": 48.5})

    telemetry = device_mgr.telemetry
    assert telemetry["battery_percent"] == 85
    assert telemetry["cpu_temp_c"] == 48.5
