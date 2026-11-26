from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Any, Optional
import json
import logging
import sqlite3
import threading
import time

from backend.config.settings import get_settings

logger = logging.getLogger("ai_voice_assistant.memory")


class BaseMemoryStore(ABC):
    """Abstract interface for long-term memory and knowledge item storage."""

    @abstractmethod
    async def retrieve_context(self, query: str, user_id: Optional[str] = None, limit: int = 3) -> List[str]:
        """Retrieve relevant long-term memory snippets matching the query."""
        pass

    @abstractmethod
    async def store_fact(self, key: str, value: Any, user_id: Optional[str] = None, consent: bool = False) -> bool:
        """Save a long-term user fact or preference (requires consent for default_user)."""
        pass

    @abstractmethod
    async def clear_memories(self, user_id: Optional[str] = None) -> bool:
        """Clear all stored long-term memory."""
        pass


class InMemoryStore(BaseMemoryStore):
    """Default lightweight in-memory store for user preferences and facts."""

    def __init__(self):
        self._user_facts: Dict[str, Dict[str, Any]] = {}

    async def retrieve_context(self, query: str, user_id: Optional[str] = None, limit: int = 3) -> List[str]:
        if not user_id or user_id == "default_user":
            # Safety & Privacy: Do not share unpartitioned facts across household members
            return []
        uid = user_id
        facts = self._user_facts.get(uid, {})
        snippets = [f"{k}: {v}" for k, v in facts.items()]
        return snippets[:limit]

    async def store_fact(self, key: str, value: Any, user_id: Optional[str] = None, consent: bool = False) -> bool:
        if not user_id or user_id == "default_user":
            if not consent:
                logger.warning("Refused storing unauthenticated fact for default_user without explicit consent.")
                return False
            uid = "default_user"
        else:
            uid = user_id

        # Sensitive disclosure filter: do not persist health/trauma/marital conflict
        text_check = f"{key} {value}".lower()
        if any(w in text_check for w in ("depress", "suicid", "abuse", "medic", "mental", "violenc", "assault")):
            logger.warning(f"Refused persisting sensitive disclosure in long-term fact memory: {key}")
            return False

        if uid not in self._user_facts:
            self._user_facts[uid] = {}
        self._user_facts[uid][key] = value
        logger.info(f"Stored long-term memory fact for [{uid}]: {key}")
        return True

    async def clear_memories(self, user_id: Optional[str] = None) -> bool:
        uid = user_id or "default_user"
        if uid in self._user_facts:
            del self._user_facts[uid]
            return True
        return False


class SQLiteMemoryStore(BaseMemoryStore):
    """Persistent SQLite storage for long-term user facts and multi-turn session history."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            if self.db_path != ":memory:":
                cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_facts (
                    user_id TEXT NOT NULL,
                    fact_key TEXT NOT NULL,
                    fact_value TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (user_id, fact_key)
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    last_active_at REAL NOT NULL
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS session_messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    source TEXT NOT NULL
                );
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_session_messages_sid_ts
                ON session_messages (session_id, timestamp);
                """
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    async def retrieve_context(self, query: str, user_id: Optional[str] = None, limit: int = 3) -> List[str]:
        if not user_id or user_id == "default_user":
            # Safety & Privacy: Do not share unpartitioned facts across household members
            return []
        uid = user_id
        with self._lock:
            rows = self._conn.execute(
                "SELECT fact_key, fact_value FROM user_facts WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
                (uid, limit),
            ).fetchall()
        snippets = []
        for row in rows:
            try:
                val = json.loads(row["fact_value"])
            except Exception:
                val = row["fact_value"]
            snippets.append(f"{row['fact_key']}: {val}")
        return snippets

    async def store_fact(self, key: str, value: Any, user_id: Optional[str] = None, consent: bool = False) -> bool:
        if not user_id or user_id == "default_user":
            if not consent:
                logger.warning("Refused storing unauthenticated fact for default_user without explicit consent.")
                return False
            uid = "default_user"
        else:
            uid = user_id

        # Sensitive disclosure filter: do not persist health/trauma/marital conflict
        text_check = f"{key} {value}".lower()
        if any(w in text_check for w in ("depress", "suicid", "abuse", "medic", "mental", "violenc", "assault")):
            logger.warning(f"Refused persisting sensitive disclosure in long-term fact memory: {key}")
            return False

        serialized = json.dumps(value, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO user_facts (user_id, fact_key, fact_value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, fact_key) DO UPDATE SET
                    fact_value = excluded.fact_value,
                    updated_at = excluded.updated_at;
                """,
                (uid, key, serialized, time.time()),
            )
            self._conn.commit()
        logger.info(f"Persisted long-term memory fact for [{uid}]: {key}")
        return True

    async def clear_memories(self, user_id: Optional[str] = None) -> bool:
        uid = user_id or "default_user"
        with self._lock:
            cur = self._conn.execute("DELETE FROM user_facts WHERE user_id = ?", (uid,))
            self._conn.commit()
            return cur.rowcount > 0

    def upsert_session(self, session_id: str, created_at: float, last_active_at: float) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sessions (session_id, created_at, last_active_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    last_active_at = excluded.last_active_at;
                """,
                (session_id, created_at, last_active_at),
            )
            self._conn.commit()

    def append_session_message(
        self,
        session_id: str,
        msg_id: str,
        role: str,
        text: str,
        timestamp: float,
        source: str,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO session_messages (id, session_id, role, text, timestamp, source)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (msg_id, session_id, role, text, timestamp, source),
            )
            self._conn.commit()

    def load_session_messages(self, session_id: str, limit: int = 25) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, role, text, timestamp, source
                FROM session_messages
                WHERE session_id = ?
                ORDER BY timestamp DESC, rowid DESC
                LIMIT ?;
                """,
                (session_id, limit),
            ).fetchall()
        # Return chronologically oldest -> newest
        return [
            {
                "id": row["id"],
                "role": row["role"],
                "text": row["text"],
                "timestamp": row["timestamp"],
                "source": row["source"],
            }
            for row in reversed(rows)
        ]

    def clear_session_messages(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))
            self._conn.commit()

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            self._conn.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))
            cur = self._conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            self._conn.commit()
            return cur.rowcount > 0


_memory_store_instance: Optional[BaseMemoryStore] = None


def get_memory_store() -> BaseMemoryStore:
    """Singleton getter for configured BaseMemoryStore (SQLite persistent or InMemory)."""
    global _memory_store_instance
    if _memory_store_instance is None:
        settings = get_settings()
        if getattr(settings, "session_persistence_enabled", True) and getattr(settings, "session_db_path", ""):
            try:
                _memory_store_instance = SQLiteMemoryStore(settings.session_db_path)
            except Exception as exc:
                logger.warning(f"SQLiteMemoryStore unavailable ({exc}); falling back to InMemoryStore.")
                _memory_store_instance = InMemoryStore()
        else:
            _memory_store_instance = InMemoryStore()
    return _memory_store_instance
