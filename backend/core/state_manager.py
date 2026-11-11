import asyncio
import logging
import time
from enum import Enum
from typing import Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("ai_voice_assistant.state")


class AssistantState(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"


# Valid standard transitions: (from_state, to_state)
VALID_TRANSITIONS: Set[Tuple[AssistantState, AssistantState]] = {
    (AssistantState.IDLE, AssistantState.LISTENING),
    (AssistantState.IDLE, AssistantState.THINKING),
    (AssistantState.LISTENING, AssistantState.THINKING),
    (AssistantState.LISTENING, AssistantState.IDLE),
    (AssistantState.THINKING, AssistantState.SPEAKING),
    (AssistantState.THINKING, AssistantState.IDLE),
    (AssistantState.THINKING, AssistantState.ERROR),
    (AssistantState.SPEAKING, AssistantState.IDLE),
    (AssistantState.SPEAKING, AssistantState.ERROR),
    (AssistantState.ERROR, AssistantState.IDLE),
}


class StateManager:
    """Manages assistant states with transition validation, barge-in support, and concurrency locks."""

    def __init__(self):
        self._state: AssistantState = AssistantState.IDLE
        self._lock = asyncio.Lock()
        self._session_locks: Dict[str, asyncio.Lock] = {}
        self._session_states: Dict[str, AssistantState] = {}
        self._session_tasks: Dict[str, asyncio.Task] = {}
        self._listeners: List[Callable[[AssistantState, dict], None]] = []
        self._last_state_change: float = time.time()
        self._current_task: Optional[asyncio.Task] = None

    @property
    def current_state(self) -> AssistantState:
        """Get the current global state."""
        return self._state

    def get_session_state(self, session_id: Optional[str] = None) -> AssistantState:
        """Get the current state for a specific session/device, falling back to global state."""
        if session_id and session_id in self._session_states:
            return self._session_states[session_id]
        return self._state

    @property
    def is_busy(self) -> bool:
        """Return True if assistant is actively transcribing or generating."""
        # Auto-reset if stuck in active state for > 15s without activity
        if self._state not in (AssistantState.IDLE, AssistantState.ERROR) and (time.time() - self._last_state_change > 15.0):
            logger.warning(f"State {self._state.value} timed out after 15s. Auto-resetting to IDLE.")
            self._state = AssistantState.IDLE
        return self._state in (AssistantState.LISTENING, AssistantState.THINKING)

    def register_listener(self, listener: Callable[[AssistantState, dict], None]) -> None:
        """Register a callback for state change events."""
        self._listeners.append(listener)

    def set_state(
        self,
        new_state: AssistantState,
        barge_in: bool = False,
        metadata: Optional[dict] = None,
        session_id: Optional[str] = None,
    ) -> bool:
        """Set state with validation, updating optional per-session state independently."""
        meta = dict(metadata or {})
        if session_id:
            meta.setdefault("session_id", session_id)
            prev_session_state = self._session_states.get(session_id, AssistantState.IDLE)
            if (
                prev_session_state != new_state
                and (
                    (prev_session_state, new_state) in VALID_TRANSITIONS
                    or new_state in (AssistantState.IDLE, AssistantState.ERROR)
                    or (barge_in and prev_session_state == AssistantState.SPEAKING and new_state == AssistantState.LISTENING)
                )
            ):
                self._session_states[session_id] = new_state

        if self._state == new_state:
            return True

        # Check transition validity
        is_valid = (self._state, new_state) in VALID_TRANSITIONS
        if not is_valid and barge_in and self._state == AssistantState.SPEAKING and new_state == AssistantState.LISTENING:
            is_valid = True
            logger.info("⚡ Barge-in triggered: SPEAKING -> LISTENING")

        # Allow forced reset to IDLE or ERROR from any state
        if new_state in (AssistantState.IDLE, AssistantState.ERROR):
            is_valid = True

        if not is_valid:
            logger.warning(f"Invalid state transition attempted: {self._state.value} -> {new_state.value}. Rejecting.")
            return False

        old_state = self._state
        self._state = new_state
        self._last_state_change = time.time()
        logger.info(f"State transitioned: {old_state.value} -> {new_state.value}")

        for callback in self._listeners:
            try:
                callback(new_state, meta)
            except Exception as e:
                logger.error(f"Error in state listener: {e}")

        return True

    def acquire_lock(self, session_id: Optional[str] = None) -> asyncio.Lock:
        """Return per-session/per-device asyncio.Lock so concurrent devices never block each other."""
        sid = (session_id or "").strip()
        if not sid:
            return self._lock
        if sid not in self._session_locks:
            self._session_locks[sid] = asyncio.Lock()
        return self._session_locks[sid]

    def cancel_active_task(self, session_id: Optional[str] = None) -> None:
        """Cancel active task for a specific session (or global fallback on barge-in / Stop)."""
        if session_id:
            sess_task = self._session_tasks.get(session_id)
            if sess_task and not sess_task.done():
                logger.info(f"Canceling active assistant task for session [{session_id}].")
                sess_task.cancel()
            self.set_state(AssistantState.IDLE, metadata={"reason": "cancelled"}, session_id=session_id)
            return

        if self._current_task and not self._current_task.done():
            logger.info("Canceling active assistant background task.")
            self._current_task.cancel()
        self.set_state(AssistantState.IDLE, metadata={"reason": "cancelled"})

    def set_active_task(self, task: asyncio.Task, session_id: Optional[str] = None) -> None:
        """Track current running task per-session and globally for cancellation."""
        self._current_task = task
        if session_id:
            self._session_tasks[session_id] = task

    def reset_to_idle(self, session_id: Optional[str] = None) -> None:
        """Force state reset to IDLE."""
        self.set_state(AssistantState.IDLE, session_id=session_id)


_state_manager_instance: Optional[StateManager] = None


def get_state_manager() -> StateManager:
    """Singleton getter for StateManager."""
    global _state_manager_instance
    if _state_manager_instance is None:
        _state_manager_instance = StateManager()
    return _state_manager_instance
