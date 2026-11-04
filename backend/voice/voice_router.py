import logging
from typing import Optional
from backend.config.settings import get_settings, Settings
from backend.voice.language_detector import get_language_detector, LanguageType

logger = logging.getLogger("ai_voice_assistant.voice_router")


class VoiceRouter:
    """Selects the best TTS neural voice based on language detection and user preferences."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.detector = get_language_detector()

    def route_voice(self, text: str, user_override: Optional[str] = None) -> str:
        """Return the optimal Edge-TTS voice string."""
        if user_override and user_override.strip():
            return user_override.strip()

        lang = self.detector.detect(text)
        logger.info(f"Language classified as [{lang.value}] for voice routing.")

        if lang == LanguageType.HINDI:
            return self.settings.tts_voice_hi  # hi-IN-SwaraNeural
        elif lang in (LanguageType.HINGLISH, LanguageType.MIXED):
            return self.settings.tts_voice_in  # en-IN-NeerjaNeural
        elif lang == LanguageType.ENGLISH:
            # If user preferred US English or Indian English
            if self.settings.language_mode == "en":
                return self.settings.tts_voice_en
            return self.settings.tts_voice
        else:
            return self.settings.tts_voice


_voice_router_instance = None


def get_voice_router() -> VoiceRouter:
    """Singleton getter for VoiceRouter."""
    global _voice_router_instance
    if _voice_router_instance is None:
        _voice_router_instance = VoiceRouter()
    return _voice_router_instance
