import os
import re
import time
import uuid
import logging
from pathlib import Path
from typing import Optional
import edge_tts

from backend.config.settings import get_settings, Settings

logger = logging.getLogger("ai_voice_assistant.tts")

TEMP_AUDIO_DIR = Path(__file__).resolve().parent.parent / "temp_audio"

# Common Hinglish marker words
HINGLISH_WORDS = {
    "aap", "kaise", "hai", "kya", "kar", "rahe", "ho", "mera", "naam",
    "batao", "shukriya", "dhanyawad", "theek", "achha", "bolo", "namaste",
    "suno", "karo", "nahi", "haan", "kaun", "kab", "kahan", "kyun", "wala"
}


class TextToSpeechService:
    """Service for synthesizing speech audio with multilingual voice detection."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        TEMP_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        self._cleanup_old_files()

    def _cleanup_old_files(self, max_age_seconds: int = 1800) -> None:
        """Remove temporary audio files older than max_age_seconds."""
        now = time.time()
        try:
            for file_path in TEMP_AUDIO_DIR.glob("*.mp3"):
                if file_path.is_file():
                    if now - file_path.stat().st_mtime > max_age_seconds:
                        try:
                            file_path.unlink()
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"Error during audio temp cleanup: {e}")

    def detect_best_voice(self, text: str) -> str:
        """Auto-detect language and return the optimal neural voice for Hindi, Hinglish, or English."""
        # 1. Check for Devanagari script (Hindi characters)
        if re.search(r"[\u0900-\u097F]", text):
            return self.settings.tts_voice_hi  # e.g. hi-IN-SwaraNeural

        # 2. Check for Hinglish latin words
        words = set(re.findall(r"\b[a-zA-Z]+\b", text.lower()))
        hinglish_matches = words.intersection(HINGLISH_WORDS)
        if len(hinglish_matches) >= 1:
            return self.settings.tts_voice_in  # e.g. en-IN-NeerjaNeural

        # 3. Default to Indian English / Hinglish or US English based on configuration
        return self.settings.tts_voice

    async def synthesize_to_file(
        self,
        text: str,
        voice: Optional[str] = None,
        rate: Optional[str] = None,
        pitch: Optional[str] = None,
    ) -> Optional[str]:
        """Synthesize text to an MP3 file with language-aware voice selection."""
        clean_text = text.strip()
        if not clean_text:
            return None

        self._cleanup_old_files()

        # Pick voice automatically if not explicitly provided
        voice_to_use = voice or self.detect_best_voice(clean_text)
        rate_to_use = rate or self.settings.tts_rate
        pitch_to_use = pitch or self.settings.tts_pitch

        filename = f"tts_{uuid.uuid4().hex[:12]}.mp3"
        output_path = TEMP_AUDIO_DIR / filename
        wav_path = output_path.with_suffix(".wav")

        try:
            logger.info(f"Synthesizing ({len(clean_text)} chars) with voice [{voice_to_use}]...")
            communicate = edge_tts.Communicate(
                text=clean_text,
                voice=voice_to_use,
                rate=rate_to_use,
                pitch=pitch_to_use,
            )
            await communicate.save(str(output_path))

            # Automatically convert to 16-bit PCM WAV for ESP32 hardware streaming
            try:
                import miniaudio, wave
                audio_data = miniaudio.mp3_read_file_s16(str(output_path))
                with wave.open(str(wav_path), "wb") as wav_file:
                    wav_file.setnchannels(audio_data.nchannels)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(audio_data.sample_rate)
                    wav_file.writeframes(audio_data.samples.tobytes())
                logger.info(f"WAV audio generated for hardware: {wav_path.name}")
            except Exception as wav_err:
                logger.warning(f"Could not create WAV mirror for ESP32: {wav_err}")

            return filename
        except Exception as e:
            logger.error(f"Failed to synthesize audio with edge-tts: {e}")
            # Fallback to default voice if regional voice encountered an issue
            if voice_to_use != self.settings.tts_voice_en:
                try:
                    logger.info(f"Retrying TTS with fallback voice {self.settings.tts_voice_en}...")
                    communicate = edge_tts.Communicate(text=clean_text, voice=self.settings.tts_voice_en)
                    await communicate.save(str(output_path))
                    return filename
                except Exception as fallback_err:
                    logger.error(f"Fallback TTS failed: {fallback_err}")
            return None


_tts_service_instance: Optional[TextToSpeechService] = None


def get_tts_service() -> TextToSpeechService:
    """Singleton getter for TextToSpeechService."""
    global _tts_service_instance
    if _tts_service_instance is None:
        _tts_service_instance = TextToSpeechService()
    return _tts_service_instance
