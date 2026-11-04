import time
import uuid
import logging
from typing import Dict, Optional, Any
from backend.core.conversation import ConversationManager
from backend.config.settings import get_settings

logger = logging.getLogger("ai_voice_assistant.session")


class Session:
    """Represents a single user/device conversation session with generation tracking."""

    def __init__(self, session_id: str, max_history: int = 25):
        self.session_id = session_id
        self.conversation = ConversationManager(max_history=max_history)
        self.created_at = time.time()
        self.last_active_at = time.time()
        self.metadata: Dict[str, Any] = {}
        
        # Generation tracking for safe cancellation and stale response rejection
        self._generation_counter: int = 0
        self.active_generation_id: str = f"gen_{self._generation_counter}"
        self._cancelled_generations: set[str] = set()

    def touch(self) -> None:
        """Update last active timestamp."""
        self.last_active_at = time.time()

    def new_generation(self) -> str:
        """Create a new generation ID, automatically superseding and invalidating previous generations."""
        self._generation_counter += 1
        new_gen_id = f"gen_{self._generation_counter}"
        old_gen_id = self.active_generation_id
        self._cancelled_generations.add(old_gen_id)
        self.active_generation_id = new_gen_id
        logger.info(f"[{self.session_id}] New generation created: {new_gen_id} (Supersedes: {old_gen_id})")
        return new_gen_id

    def is_current_generation(self, generation_id: Optional[str]) -> bool:
        """Return True if generation_id matches the active generation and is not cancelled."""
        if not generation_id:
            return False
        return generation_id == self.active_generation_id and generation_id not in self._cancelled_generations

    def cancel_current_generation(self) -> str:
        """Explicitly cancel the current generation."""
        cancelled_id = self.active_generation_id
        self._cancelled_generations.add(cancelled_id)
        logger.info(f"[{self.session_id}] Generation cancelled: {cancelled_id}")
        return cancelled_id


class SessionManager:
    """Thread-safe manager for user conversation sessions."""

    def __init__(self, session_ttl_seconds: int = 86400):
        self._sessions: Dict[str, Session] = {}
        self.session_ttl = session_ttl_seconds
        self.settings = get_settings()

    def get_or_create_session(self, session_id: Optional[str] = None) -> Session:
        """Get an existing session or create a new one."""
        self._cleanup_expired()

        sid = (session_id or "").strip()
        if not sid:
            sid = f"sess_{uuid.uuid4().hex[:12]}"

        if sid not in self._sessions:
            logger.info(f"Creating new session: {sid}")
            self._sessions[sid] = Session(
                session_id=sid,
                max_history=self.settings.max_history_turns,
            )

        session = self._sessions[sid]
        session.touch()
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Retrieve an existing session without creating one."""
        return self._sessions.get(session_id)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"Deleted session: {session_id}")
            return True
        return False

    def _cleanup_expired(self) -> None:
        """Remove sessions older than TTL."""
        now = time.time()
        expired = [
            sid for sid, s in self._sessions.items()
            if now - s.last_active_at > self.session_ttl
        ]
        for sid in expired:
            del self._sessions[sid]


_session_manager_instance: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Singleton getter for SessionManager."""
    global _session_manager_instance
    if _session_manager_instance is None:
        _session_manager_instance = SessionManager()
    return _session_manager_instance
