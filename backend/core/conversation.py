import time
import uuid
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field


class Message(BaseModel):
    """Single turn message representation."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    role: str  # "user" or "assistant"
    text: str
    timestamp: float = Field(default_factory=time.time)
    source: str = "text"  # "text" | "voice"


class ConversationManager:
    """Manages multi-turn conversation memory with size limits and formatting."""

    def __init__(self, max_history: int = 30):
        self.max_history = max_history
        self._history: List[Message] = []

    def add_user_message(self, text: str, source: str = "text") -> Message:
        """Add user message to history."""
        msg = Message(role="user", text=text, source=source)
        self._history.append(msg)
        self._trim_history()
        return msg

    def add_assistant_message(self, text: str) -> Message:
        """Add assistant response to history."""
        msg = Message(role="assistant", text=text, source="assistant")
        self._history.append(msg)
        self._trim_history()
        return msg

    def get_history(self) -> List[Dict[str, Any]]:
        """Return list of messages as dictionaries."""
        return [msg.model_dump() for msg in self._history]

    def get_gemini_context(self) -> List[Dict[str, str]]:
        """Format history for Gemini API consumption (excludes the latest prompt if needed)."""
        gemini_history = []
        for msg in self._history:
            gemini_history.append({
                "role": "user" if msg.role == "user" else "model",
                "text": msg.text,
            })
        return gemini_history

    def clear(self) -> None:
        """Clear all conversation history."""
        self._history.clear()

    def _trim_history(self) -> None:
        """Keep history within max allowed turns."""
        if len(self._history) > self.max_history:
            self._history = self._history[-self.max_history:]


_conversation_manager_instance: Optional[ConversationManager] = None


def get_conversation_manager() -> ConversationManager:
    """Singleton getter for ConversationManager."""
    global _conversation_manager_instance
    if _conversation_manager_instance is None:
        _conversation_manager_instance = ConversationManager()
    return _conversation_manager_instance
