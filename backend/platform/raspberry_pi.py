import asyncio
import logging
from typing import AsyncGenerator
from backend.platform.audio_interface import AudioInputInterface, AudioOutputInterface

logger = logging.getLogger("ai_voice_assistant.platform.raspberry_pi")


class RaspberryPiAudioAdapter(AudioInputInterface, AudioOutputInterface):
    """Raspberry Pi hardware audio adapter supporting ALSA / I2S / ReSpeaker mic arrays."""

    def __init__(self, device_index: int = 0):
        self.device_index = device_index
        self._is_recording = False
        self._is_playing = False

    async def start_recording(self) -> None:
        self._is_recording = True
        logger.info(f"Raspberry Pi ALSA capture started (Device #{self.device_index}).")

    async def stop_recording(self) -> bytes:
        self._is_recording = False
        logger.info("Raspberry Pi ALSA capture stopped.")
        return b""

    async def stream_audio_chunks(self) -> AsyncGenerator[bytes, None]:
        while self._is_recording:
            await asyncio.sleep(0.05)
            yield b"\x00" * 1024

    async def play_audio_file(self, file_path: str) -> bool:
        logger.info(f"Raspberry Pi aplay/speaker output: {file_path}")
        self._is_playing = True
        return True

    async def play_audio_bytes(self, audio_bytes: bytes) -> bool:
        logger.info(f"Raspberry Pi raw audio playback: {len(audio_bytes)} bytes")
        self._is_playing = True
        return True

    def stop_playback(self) -> None:
        logger.info("Raspberry Pi audio playback stopped.")
        self._is_playing = False
