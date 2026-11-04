import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger("ai_voice_assistant.wake_word")


class BaseWakeWordService(ABC):
    """Abstract interface for local Wake Word / Keyword Spotting engines."""

    @abstractmethod
    async def process_audio_frame(self, frame_bytes: bytes) -> bool:
        """Process a small PCM audio frame and return True if wake word is detected."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset internal buffer / detector state."""
        pass


class KeywordWakeWordStub(BaseWakeWordService):
    """Default lightweight keyword stub for development and testing."""

    def __init__(self, keyword: str = "hey aether"):
        self.keyword = keyword.lower()
        self.is_active = False

    async def process_audio_frame(self, frame_bytes: bytes) -> bool:
        # Stub does not perform heavy DSP; ready for hardware wake word engine
        return False

    def reset(self) -> None:
        self.is_active = False


class PorcupineWakeWordService(BaseWakeWordService):
    """Picovoice Porcupine Wake Word Service (Ideal for Raspberry Pi 5 & Windows)."""

    def __init__(self, access_key: str = "", keyword: str = "jarvis"):
        self.access_key = access_key
        self.keyword = keyword
        self._porcupine = None

    async def process_audio_frame(self, frame_bytes: bytes) -> bool:
        logger.info("Porcupine processing frame stub.")
        return False

    def reset(self) -> None:
        pass


class OpenWakeWordService(BaseWakeWordService):
    """openWakeWord Open-source Neural Wake Word Service."""

    def __init__(self, model_name: str = "hey_jarvis"):
        self.model_name = model_name

    async def process_audio_frame(self, frame_bytes: bytes) -> bool:
        return False

    def reset(self) -> None:
        pass


_wake_word_service_instance: Optional[BaseWakeWordService] = None


def get_wake_word_service() -> BaseWakeWordService:
    """Singleton getter for WakeWordService."""
    global _wake_word_service_instance
    if _wake_word_service_instance is None:
        _wake_word_service_instance = KeywordWakeWordStub()
    return _wake_word_service_instance
