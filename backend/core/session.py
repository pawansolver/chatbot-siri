import time
import uuid
import logging
from typing import Dict, Optional, Any, Callable
from backend.core.conversation import ConversationManager, Message
from backend.core.memory import SQLiteMemoryStore, get_memory_store
from backend.config.settings import get_settings

logger = logging.getLogger("ai_voice_assistant.session")


class Session:
    """Represents a single user/device conversation session with generation tracking."""

    def __init__(
        self,
        session_id: str,
        max_history: int = 25,
        on_message_added: Optional[Callable[[Message], None]] = None,
        on_cleared: Optional[Callable[[], None]] = None,
    ):
        self.session_id = session_id
        self.conversation = ConversationManager(
            max_history=max_history,
            on_message_added=on_message_added,
            on_cleared=on_cleared,
        )
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
    """Thread-safe manager for user conversation sessions with optional SQLite persistence."""

    def __init__(
        self,
        session_ttl_seconds: int = 86400,
        store: Optional[SQLiteMemoryStore] = None,
        db_path: Optional[str] = None,
        enable_persistence: Optional[bool] = None,
    ):
        self._sessions: Dict[str, Session] = {}
        self.session_ttl = session_ttl_seconds
        self.settings = get_settings()
        self._store: Optional[SQLiteMemoryStore] = None

        persist = (
            enable_persistence
            if enable_persistence is not None
            else bool(getattr(self.settings, "session_persistence_enabled", True))
        )
        if persist:
            if store is not None:
                self._store = store
            elif db_path:
                self._store = SQLiteMemoryStore(db_path)
            else:
                candidate = get_memory_store()
                if isinstance(candidate, SQLiteMemoryStore):
                    self._store = candidate

    def _build_session(self, sid: str) -> Session:
        store = self._store
        if store is None:
            return Session(session_id=sid, max_history=self.settings.max_history_turns)

        def _on_msg(msg: Message) -> None:
            try:
                store.append_session_message(
                    session_id=sid,
                    msg_id=msg.id,
                    role=msg.role,
                    text=msg.text,
                    timestamp=msg.timestamp,
                    source=msg.source,
                )
            except Exception as err:
                logger.warning(f"Failed persisting message for [{sid}]: {err}")

        def _on_clear() -> None:
            try:
                store.clear_session_messages(sid)
            except Exception as err:
                logger.warning(f"Failed clearing persisted messages for [{sid}]: {err}")

        session = Session(
            session_id=sid,
            max_history=self.settings.max_history_turns,
            on_message_added=_on_msg,
            on_cleared=_on_clear,
        )
        try:
            past_rows = store.load_session_messages(sid, limit=self.settings.max_history_turns)
            if past_rows:
                hydrated = [Message(**row) for row in past_rows]
                session.conversation.load_messages(hydrated)
                logger.info(f"Restored {len(hydrated)} messages for session [{sid}] from SQLite.")
            store.upsert_session(sid, session.created_at, session.last_active_at)
        except Exception as err:
            logger.warning(f"Failed loading session [{sid}] from SQLite: {err}")
        return session

    def get_or_create_session(self, session_id: Optional[str] = None) -> Session:
        """Get an existing session or create/hydrate one from SQLite."""
        self._cleanup_expired()

        sid = (session_id or "").strip()
        if not sid:
            sid = f"sess_{uuid.uuid4().hex[:12]}"

        if sid not in self._sessions:
            logger.info(f"Creating new session: {sid}")
            self._sessions[sid] = self._build_session(sid)

        session = self._sessions[sid]
        session.touch()
        if self._store is not None:
            try:
                self._store.upsert_session(sid, session.created_at, session.last_active_at)
            except Exception as err:
                logger.warning(f"Failed updating session activity [{sid}]: {err}")
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Retrieve an existing session without creating one."""
        return self._sessions.get(session_id)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session from memory and persistent store."""
        existed = session_id in self._sessions
        if existed:
            del self._sessions[session_id]
        if self._store is not None:
            existed = self._store.delete_session(session_id) or existed
        if existed:
            logger.info(f"Deleted session: {session_id}")
        return existed

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
