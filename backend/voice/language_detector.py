import re
from enum import Enum
from typing import Set, Tuple, Dict, Any
import logging

logger = logging.getLogger("ai_voice_assistant.language")


class LanguageType(str, Enum):
    HINDI = "Hindi"
    ENGLISH = "English"
    HINGLISH = "Hinglish"
    MIXED = "Mixed"
    UNKNOWN = "Unknown"


# Comprehensive Hinglish markers (Latin script words commonly used in Hindi/Hinglish speech)
HINGLISH_VOCABULARY: Set[str] = {
    "aap", "kaise", "kaisa", "kaisi", "hai", "hain", "kya", "kar", "karo", "rahe",
    "raha", "rahi", "ho", "mera", "meri", "mere", "naam", "batao", "bataiye", "shukriya",
    "dhanyawad", "theek", "thik", "achha", "accha", "bolo", "namaste", "namaskar", "suno",
    "sunao", "karna", "nahi", "nahin", "haan", "kaun", "kab", "kahan", "kaha", "kyun",
    "kyu", "wala", "wali", "wale", "kuch", "kuchh", "bahut", "bohot", "acche", "mujhe",
    "tujhe", "hum", "humko", "apna", "apni", "kaam", "chahiye", "hoga", "hogi", "honge",
    "din", "raat", "subah", "shaam", "kitna", "kitni", "bhai", "yaar", "madad", "samajh",
    "pata", "aaj", "kal", "parso", "kripya", "dekho", "dekha", "sahi", "galat", "kaafi"
}

ENGLISH_COMMON_WORDS: Set[str] = {
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "i", "it", "for",
    "not", "on", "with", "he", "as", "you", "do", "at", "this", "but", "his", "by",
    "from", "they", "we", "say", "her", "she", "or", "an", "will", "my", "one", "all",
    "would", "there", "their", "what", "so", "up", "out", "if", "about", "who", "get",
    "which", "go", "me", "when", "make", "can", "like", "time", "no", "just", "him",
    "know", "take", "people", "into", "year", "your", "good", "some", "could", "them",
    "see", "other", "than", "then", "now", "look", "only", "come", "its", "over",
    "think", "also", "back", "after", "use", "two", "how", "our", "work", "first",
    "well", "way", "even", "new", "want", "because", "any", "these", "give", "day",
    "most", "us", "weather", "assistant", "system", "please", "tell", "explain", "help"
}


class LanguageDetector:
    """Classifies input text into Hindi, English, Hinglish, Mixed, or Unknown."""

    def __init__(self):
        self._devanagari_regex = re.compile(r"[\u0900-\u097F]")
        self._latin_words_regex = re.compile(r"\b[a-zA-Z']+\b")

    def detect(self, text: str) -> LanguageType:
        """Classify text into a LanguageType."""
        clean_text = text.strip()
        if not clean_text:
            return LanguageType.UNKNOWN

        # 1. Check for Devanagari script (Hindi characters)
        devanagari_chars = self._devanagari_regex.findall(clean_text)
        total_letters = len([c for c in clean_text if c.isalpha() or ('\u0900' <= c <= '\u097F')])
        devanagari_ratio = len(devanagari_chars) / max(1, total_letters)

        if devanagari_ratio > 0.6:
            return LanguageType.HINDI
        elif devanagari_ratio > 0.15:
            return LanguageType.MIXED

        # 2. Analyze Latin-script words
        words = [w.lower() for w in self._latin_words_regex.findall(clean_text)]
        if not words:
            return LanguageType.UNKNOWN

        total_words = len(words)
        hinglish_hits = sum(1 for w in words if w in HINGLISH_VOCABULARY)
        english_hits = sum(1 for w in words if w in ENGLISH_COMMON_WORDS)

        hinglish_score = hinglish_hits / total_words
        english_score = english_hits / total_words

        # Check for mixed Devanagari + English/Hinglish
        if len(devanagari_chars) > 0 and (hinglish_hits > 0 or english_hits > 0):
            return LanguageType.MIXED

        if hinglish_hits >= 2 or (hinglish_hits == 1 and total_words <= 3) or (hinglish_score > 0.25 and hinglish_hits > 0):
            if english_hits >= 2 and english_score > hinglish_score:
                return LanguageType.MIXED
            return LanguageType.HINGLISH

        if english_hits > 0 or total_words >= 1:
            return LanguageType.ENGLISH

        return LanguageType.UNKNOWN


_language_detector_instance = None


def get_language_detector() -> LanguageDetector:
    """Singleton getter for LanguageDetector."""
    global _language_detector_instance
    if _language_detector_instance is None:
        _language_detector_instance = LanguageDetector()
    return _language_detector_instance
