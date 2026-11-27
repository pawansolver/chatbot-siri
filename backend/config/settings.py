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

    # Diffy Agent API Gateway Configuration (Single Brain)
    diffy_agent_api_url: str = "http://127.0.0.1:3001"
    device_token: str = ""  # Per-device paired token (fluai_dev_...) issued by /v1/devices/pair
    use_agent_gateway: bool = True

    # Legacy Gemini Configuration (kept optional only for legacy unit test compatibility)
    gemini_api_key: str = ""
    gemini_model: str = "diffy-agent"
    available_models: List[str] = [
        "diffy-agent",
        "gemini-flash-lite-latest",
        "gemini-2.5-flash",
    ]

    # Legacy MCP settings (unused in Device Gateway mode)
    mcp_enabled: bool = True
    mcp_server_url: str = "http://127.0.0.1:3001/mcp"
    mcp_mode: str = "hybrid"
    mcp_api_key: str = ""
    mcp_timeout_seconds: float = 8.0
    mcp_cache_ttl_seconds: float = 600.0
    mcp_max_tool_turns: int = 4

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
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False  # Disable reload in production — prevents socket drops
    cors_origins: List[str] = ["*"]  # Allow ESP32 and all LAN clients
    device_api_key: str = ""  # Optional X-API-Key header required on /api/* when non-empty

    # Short-lived Device State Only (Long-term memory moved to Diffy Agent API Neon Postgres)
    session_persistence_enabled: bool = False
    session_db_path: str = str(BASE_DIR / "backend" / "data" / "sessions.db")

    # Limits & Protection
    rate_limit_per_minute: int = 120  # Increased for ESP32 hardware device (was 30)
    max_message_length: int = 1500
    max_audio_size_bytes: int = 10 * 1024 * 1024  # 10MB
    max_history_turns: int = 25
    request_timeout: float = 60.0  # 60s timeout — Gemini + TTS can take up to 10s

    # Assistant Personality (Multilingual Hindi, English, Hinglish - Human Empathy First)
    system_instruction: str = (
        "You are Aether, a deeply compassionate, wise, and natural human-centered AI companion and voice mediator. "
        "You fluently understand and speak English, Hindi (हिन्दी), and Hinglish. "
        "Always respond in the same language and style the user speaks (e.g. if Hindi, reply in natural Hindi; if Hinglish, reply in warm Hinglish; if English, reply in English). "
        "HUMAN-FIRST EMPATHY DIRECTIVE: When users share personal pain, relationship conflict, family stress, or emotional struggles, "
        "NEVER give cold robotic bullet points or superficial gyaan. "
        "First, deeply acknowledge and validate their emotional feeling (hurt, exhaustion, anxiety, anger) with genuine warmth. "
        "Second, guide them toward the underlying unmet need (Respect, Trust, Security, Care) without blaming anyone. "
        "Third, offer gentle, practical wisdom grounded in mutual coexistence (Vyavastha). "
        "Keep your spoken answers concise (1 to 3 warm, natural sentences) so they sound calming, patient, and engaging when spoken aloud. "
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

    @field_validator("mcp_mode")
    @classmethod
    def validate_mcp_mode(cls, v: str) -> str:
        valid_modes = ["hybrid", "strict", "off"]
        v_clean = v.lower().strip()
        if v_clean not in valid_modes:
            logger.warning(f"Invalid MCP mode '{v}'. Falling back to 'hybrid'.")
            return "hybrid"
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
            "mcp_enabled": self.mcp_enabled,
            "mcp_server_url": self.mcp_server_url,
            "mcp_mode": self.mcp_mode,
            "auth_required": bool(self.device_api_key.strip()),
            "session_persistence_enabled": self.session_persistence_enabled,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "max_message_length": self.max_message_length,
            "max_history_turns": self.max_history_turns,
        }


@lru_cache()
def get_settings() -> Settings:
    """Singleton getter for application settings."""
    return Settings()
