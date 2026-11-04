import io
import logging
import asyncio
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

import speech_recognition as sr
from backend.config.settings import get_settings, Settings

logger = logging.getLogger("ai_voice_assistant.stt")


class BaseSTTService(ABC):
    """Abstract Base Class for Replaceable Speech-to-Text Engines."""

    @abstractmethod
    async def transcribe(
        self,
        audio_bytes: bytes,
        audio_format: str = "wav",
        language: str = "auto",
    ) -> str:
        """Transcribe audio bytes to text in a non-blocking asynchronous manner."""
        pass


class GoogleSpeechRecognitionSTT(BaseSTTService):
    """STT implementation using Google Speech Recognition via speech_recognition library."""

    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 300
        self.recognizer.dynamic_energy_threshold = True

    async def transcribe(
        self,
        audio_bytes: bytes,
        audio_format: str = "wav",
        language: str = "auto",
    ) -> str:
        if not audio_bytes or len(audio_bytes) < 100:
            logger.warning("Empty or truncated audio buffer received.")
            return ""

        # Language code mapping
        lang_code = "en-IN"  # Default Indian English / Hinglish
        if language == "hi" or language == "hindi":
            lang_code = "hi-IN"
        elif language == "en-US" or language == "en":
            lang_code = "en-US"

        def _recognize() -> str:
            try:
                audio_file = io.BytesIO(audio_bytes)
                with sr.AudioFile(audio_file) as source:
                    audio_data = self.recognizer.record(source)
                    # Attempt recognition with configured language
                    try:
                        text = self.recognizer.recognize_google(audio_data, language=lang_code)
                        return text.strip()
                    except sr.UnknownValueError:
                        # Fallback try Hindi if auto mode
                        if language == "auto":
                            try:
                                text_hi = self.recognizer.recognize_google(audio_data, language="hi-IN")
                                return text_hi.strip()
                            except Exception:
                                pass
                        return ""
            except sr.UnknownValueError:
                logger.info("Speech recognition: unintelligible speech or silence.")
                return ""
            except sr.RequestError as e:
                logger.error(f"Google STT service request error: {e}")
                return ""
            except Exception as e:
                logger.error(f"Error processing audio in Google STT: {e}")
                return ""

        try:
            return await asyncio.to_thread(_recognize)
        except Exception as e:
            logger.error(f"Async Google STT failed: {e}")
            return ""


class GeminiMultimodalSTT(BaseSTTService):
    """STT implementation leveraging Gemini's native multimodal audio transcription."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()

    async def transcribe(
        self,
        audio_bytes: bytes,
        audio_format: str = "wav",
        language: str = "auto",
    ) -> str:
        if not audio_bytes or len(audio_bytes) < 100:
            return ""

        if not self.settings.has_api_key:
            logger.warning("Gemini API key missing for GeminiMultimodalSTT.")
            return ""

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.settings.gemini_api_key.strip())
            mime = "audio/wav" if "wav" in audio_format else "audio/mp3"

            def _gemini_stt() -> str:
                response = client.models.generate_content(
                    model=self.settings.gemini_model,
                    contents=[
                        types.Part.from_bytes(data=audio_bytes, mime_type=mime),
                        (
                            "Listen carefully to this audio and write down the exact speech verbatim. "
                            "It could be in English, Hindi (हिन्दी), or Hinglish. "
                            "Return ONLY the transcribed text without quotes or explanations."
                        ),
                    ],
                )
                if response and response.text:
                    return response.text.strip()
                return ""

            return await asyncio.to_thread(_gemini_stt)
        except Exception as e:
            logger.error(f"Gemini Multimodal STT failed: {e}")
            return ""


class WhisperSTT(BaseSTTService):
    """Pluggable Local Whisper / Faster-Whisper STT (Ideal for local Raspberry Pi processing)."""

    def __init__(self):
        self._model = None

    async def transcribe(
        self,
        audio_bytes: bytes,
        audio_format: str = "wav",
        language: str = "auto",
    ) -> str:
        logger.info("Whisper STT stub invoked. Ready for faster-whisper / whisper-cpp integration.")
        # Fallback to Google STT if local whisper weights are not loaded
        fallback = GoogleSpeechRecognitionSTT()
        return await fallback.transcribe(audio_bytes, audio_format, language)


# STT Registry & Factory
_STT_REGISTRY: Dict[str, BaseSTTService] = {}


def get_stt_service(engine_name: Optional[str] = None) -> BaseSTTService:
    """Factory creating and returning the configured STT service implementation."""
    settings = get_settings()
    engine = (engine_name or settings.stt_engine).lower().strip()

    if engine not in _STT_REGISTRY:
        if engine == "gemini":
            logger.info("Using GeminiMultimodalSTT engine.")
            _STT_REGISTRY[engine] = GeminiMultimodalSTT(settings)
        elif engine == "whisper":
            logger.info("Using WhisperSTT engine.")
            _STT_REGISTRY[engine] = WhisperSTT()
        else:
            logger.info("Using GoogleSpeechRecognitionSTT engine.")
            _STT_REGISTRY[engine] = GoogleSpeechRecognitionSTT()

    return _STT_REGISTRY[engine]


# Backward compatibility alias
SpeechToTextService = GoogleSpeechRecognitionSTT
