import sys
import logging
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional, Tuple

logger = logging.getLogger("ai_voice_assistant.platform")


class AudioInputInterface(ABC):
    """Abstract interface for capturing hardware microphone audio."""

    @abstractmethod
    async def start_recording(self) -> None:
        """Initialize and start recording audio from the microphone."""
        pass

    @abstractmethod
    async def stop_recording(self) -> bytes:
        """Stop recording and return captured PCM audio bytes."""
        pass

    @abstractmethod
    async def stream_audio_chunks(self) -> AsyncGenerator[bytes, None]:
        """Stream continuous audio frames (e.g. for wake-word / real-time STT)."""
        pass


class AudioOutputInterface(ABC):
    """Abstract interface for playing audio through hardware speakers."""

    @abstractmethod
    async def play_audio_file(self, file_path: str) -> bool:
        """Play an audio file on the speaker."""
        pass

    @abstractmethod
    async def play_audio_bytes(self, audio_bytes: bytes) -> bool:
        """Play raw audio bytes directly on the speaker."""
        pass

    @abstractmethod
    def stop_playback(self) -> None:
        """Interrupt and stop current audio playback immediately."""
        pass


def get_platform_audio_adapters() -> Tuple[AudioInputInterface, AudioOutputInterface]:
    """Factory creating appropriate audio adapters depending on host operating system."""
    if sys.platform.startswith("win"):
        from backend.platform.windows import WindowsAudioAdapter
        adapter = WindowsAudioAdapter()
        return adapter, adapter
    else:
        from backend.platform.raspberry_pi import RaspberryPiAudioAdapter
        adapter = RaspberryPiAudioAdapter()
        return adapter, adapter
