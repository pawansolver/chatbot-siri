import os
import logging
from functools import lru_cache
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("ai_voice_assistant.config")

# Base directory of the repository
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    """Centralized application settings with startup validation and safe exposure."""

    # Gemini Configuration
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.1-flash-lite"
    available_models: List[str] = [
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash",
        "gemini-flash-latest",
    ]

    # Voice & Language Configuration
    language_mode: str = "auto"  # auto | en | hi | hinglish
    stt_engine: str = "google"   # google | gemini | whisper
    tts_voice: str = "en-IN-NeerjaNeural"
    tts_voice_en: str = "en-US-AvaNeural"
    tts_voice_hi: str = "hi-IN-SwaraNeural"
    tts_voice_in: str = "en-IN-NeerjaNeural"
    tts_rate: str = "+0%"
    tts_pitch: str = "+0Hz"

    # Server & Network Configuration
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = True
    cors_origins: List[str] = ["http://127.0.0.1:8000", "http://localhost:8000", "http://127.0.0.1:3000"]

    # Limits & Protection
    rate_limit_per_minute: int = 30
    max_message_length: int = 1500
    max_audio_size_bytes: int = 10 * 1024 * 1024  # 10MB
    max_history_turns: int = 25
    request_timeout: float = 20.0

    # Assistant Personality (Multilingual Hindi, English, Hinglish)
    system_instruction: str = (
        "You are Aether, an intelligent, fast, and natural AI voice assistant. "
        "You fluently understand and speak English, Hindi (हिन्दी), and Hinglish. "
        "Always respond in the same language and style the user speaks (e.g. if the user speaks Hindi, reply in natural Hindi; "
        "if the user speaks Hinglish, reply in natural conversational Hinglish; if in English, reply in English). "
        "Keep your answers concise (1 to 3 sentences) so they sound crisp and engaging when spoken aloud. "
        "Avoid markdown tables, asterisks, or bulleted lists unless explicitly asked."
    )

    model_config = SettingsConfigDict(
        env_file=ENV_FILE if ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("stt_engine")
    @classmethod
    def validate_stt_engine(cls, v: str) -> str:
        valid_engines = ["google", "gemini", "whisper"]
        v_clean = v.lower().strip()
        if v_clean not in valid_engines:
            logger.warning(f"Invalid STT engine '{v}'. Falling back to 'google'.")
            return "google"
        return v_clean

    @field_validator("language_mode")
    @classmethod
    def validate_language_mode(cls, v: str) -> str:
        valid_modes = ["auto", "en", "hi", "hinglish", "en-in", "en-us"]
        v_clean = v.lower().strip()
        if v_clean not in valid_modes:
            return "auto"
        return v_clean

    @property
    def has_api_key(self) -> bool:
        """Check whether a non-empty Gemini API key is configured."""
        return bool(self.gemini_api_key and self.gemini_api_key.strip() != "")

    def get_safe_dict(self) -> Dict[str, Any]:
        """Return safe runtime configuration dictionary without leaking secrets."""
        return {
            "active_model": self.gemini_model,
            "available_models": self.available_models,
            "active_stt_engine": self.stt_engine,
            "available_stt_engines": ["google", "gemini", "whisper"],
            "active_language_mode": self.language_mode,
            "available_languages": ["auto", "hi", "en-IN", "en-US"],
            "active_voice": self.tts_voice,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "max_message_length": self.max_message_length,
            "max_history_turns": self.max_history_turns,
        }


@lru_cache()
def get_settings() -> Settings:
    """Singleton getter for application settings."""
    return Settings()
