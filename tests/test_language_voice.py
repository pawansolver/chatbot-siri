import pytest
from backend.voice.language_detector import LanguageDetector, LanguageType, get_language_detector
from backend.voice.voice_router import VoiceRouter, get_voice_router
from backend.config.settings import Settings


def test_language_detector_classifications():
    """Verify LanguageDetector classifies Hindi, English, Hinglish, and Mixed text correctly."""
    detector = get_language_detector()

    # 1. Hindi (Devanagari)
    assert detector.detect("नमस्ते! आप कैसे हैं?") == LanguageType.HINDI
    assert detector.detect("मुझे भारत का मौसम बताओ") == LanguageType.HINDI

    # 2. Hinglish (Latin Hindi)
    assert detector.detect("Aap kaise ho bhai?") == LanguageType.HINGLISH
    assert detector.detect("Mera naam Aether hai aur aapka?") == LanguageType.HINGLISH
    assert detector.detect("kya haal chaal hai") == LanguageType.HINGLISH

    # 3. Pure English
    assert detector.detect("How is the weather in Delhi today?") == LanguageType.ENGLISH
    assert detector.detect("Explain quantum computing in simple terms.") == LanguageType.ENGLISH

    # 4. Mixed Language
    assert detector.detect("Aaj ka weather kaisa hai?") == LanguageType.MIXED or detector.detect("Aaj ka weather kaisa hai?") == LanguageType.HINGLISH
    assert detector.detect("Mujhe weather बताओ") == LanguageType.MIXED

    # 5. Empty / Unknown
    assert detector.detect("") == LanguageType.UNKNOWN


def test_voice_router_selection():
    """Verify VoiceRouter maps detected languages to appropriate neural voices."""
    settings = Settings(
        tts_voice="en-IN-NeerjaNeural",
        tts_voice_hi="hi-IN-SwaraNeural",
        tts_voice_in="en-IN-NeerjaNeural",
        tts_voice_en="en-US-AvaNeural",
    )
    router = VoiceRouter(settings=settings)

    # Hindi text -> Hindi voice
    hi_voice = router.route_voice("नमस्ते आप कैसे हैं?")
    assert hi_voice == "hi-IN-SwaraNeural"

    # Hinglish text -> Indian English / Hinglish voice
    hinglish_voice = router.route_voice("Aap kaise ho?")
    assert hinglish_voice == "en-IN-NeerjaNeural"

    # Explicit user override
    custom_voice = router.route_voice("Hello world", user_override="en-GB-SoniaNeural")
    assert custom_voice == "en-GB-SoniaNeural"
