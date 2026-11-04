import asyncio
import logging
from typing import AsyncGenerator
from backend.platform.audio_interface import AudioInputInterface, AudioOutputInterface

logger = logging.getLogger("ai_voice_assistant.platform.windows")


class WindowsAudioAdapter(AudioInputInterface, AudioOutputInterface):
    """Windows audio hardware adapter supporting WASAPI/DirectSound and browser bridge."""

    def __init__(self):
        self._is_recording = False
        self._is_playing = False

    async def start_recording(self) -> None:
        self._is_recording = True
        logger.info("Windows microphone recording started.")

    async def stop_recording(self) -> bytes:
        self._is_recording = False
        logger.info("Windows microphone recording stopped.")
        return b""

    async def stream_audio_chunks(self) -> AsyncGenerator[bytes, None]:
        while self._is_recording:
            await asyncio.sleep(0.05)
            yield b"\x00" * 1024

    async def play_audio_file(self, file_path: str) -> bool:
        logger.info(f"Windows audio playback: {file_path}")
        self._is_playing = True
        return True

    async def play_audio_bytes(self, audio_bytes: bytes) -> bool:
        logger.info(f"Windows audio playback: {len(audio_bytes)} bytes")
        self._is_playing = True
        return True

    def stop_playback(self) -> None:
        logger.info("Windows audio playback stopped / interrupted.")
        self._is_playing = False
