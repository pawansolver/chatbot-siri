import io
import wave
import struct
import shutil
import logging
from typing import Tuple, Optional

logger = logging.getLogger("ai_voice_assistant.audio_normalizer")


class AudioNormalizer:
    """Normalizes and validates browser/mic audio inputs for consistent STT decoding."""

    def __init__(self):
        self.has_ffmpeg = bool(shutil.which("ffmpeg"))

    def detect_format(self, audio_bytes: bytes) -> str:
        """Identify audio format from header magic bytes."""
        if not audio_bytes or len(audio_bytes) < 12:
            return "unknown"

        # Check for RIFF WAV
        if audio_bytes[:4] == b"RIFF" and audio_bytes[8:12] == b"WAVE":
            return "wav"

        # Check for WebM / Matroska EBML
        if audio_bytes[:4] == b"\x1a\x45\xdf\xa3":
            return "webm"

        # Check for MP3 ID3 or Sync Frame
        if audio_bytes[:3] == b"ID3" or (audio_bytes[0] == 0xFF and (audio_bytes[1] & 0xE0) == 0xE0):
            return "mp3"

        # Check for OGG
        if audio_bytes[:4] == b"OggS":
            return "ogg"

        return "unknown"

    def validate_audio(self, audio_bytes: bytes, max_size_bytes: int = 10 * 1024 * 1024) -> Tuple[bool, Optional[str]]:
        """Validate audio payload size and content."""
        if not audio_bytes:
            return False, "No audio data received."

        if len(audio_bytes) < 200:
            return False, "Audio recording too short or empty."

        if len(audio_bytes) > max_size_bytes:
            return False, f"Audio file exceeds maximum allowed limit ({max_size_bytes // (1024*1024)}MB)."

        return True, None

    def normalize_to_wav(self, audio_bytes: bytes) -> Tuple[bytes, str]:
        """Convert or validate audio bytes into WAV format."""
        fmt = self.detect_format(audio_bytes)
        if fmt == "wav":
            return audio_bytes, "wav"

        if fmt in ("webm", "mp3", "ogg"):
            logger.info(f"Detected {fmt.upper()} audio format ({len(audio_bytes)} bytes).")
            # If native ffmpeg exists, we could transcode; otherwise pass along format tag
            return audio_bytes, fmt

        return audio_bytes, fmt


_audio_normalizer_instance = None


def get_audio_normalizer() -> AudioNormalizer:
    """Singleton getter for AudioNormalizer."""
    global _audio_normalizer_instance
    if _audio_normalizer_instance is None:
        _audio_normalizer_instance = AudioNormalizer()
    return _audio_normalizer_instance
