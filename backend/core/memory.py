from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import time
import logging

logger = logging.getLogger("ai_voice_assistant.memory")


class BaseMemoryStore(ABC):
    """Abstract interface for long-term memory and knowledge item storage."""

    @abstractmethod
    async def retrieve_context(self, query: str, user_id: Optional[str] = None, limit: int = 3) -> List[str]:
        """Retrieve relevant long-term memory snippets matching the query."""
        pass

    @abstractmethod
    async def store_fact(self, key: str, value: Any, user_id: Optional[str] = None) -> bool:
        """Save a long-term user fact or preference."""
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
        uid = user_id or "default_user"
        facts = self._user_facts.get(uid, {})
        snippets = [f"{k}: {v}" for k, v in facts.items()]
        return snippets[:limit]

    async def store_fact(self, key: str, value: Any, user_id: Optional[str] = None) -> bool:
        uid = user_id or "default_user"
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


_memory_store_instance: Optional[BaseMemoryStore] = None


def get_memory_store() -> BaseMemoryStore:
    """Singleton getter for BaseMemoryStore."""
    global _memory_store_instance
    if _memory_store_instance is None:
        _memory_store_instance = InMemoryStore()
    return _memory_store_instance
