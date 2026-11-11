import array
import concurrent.futures
import io
import logging
import asyncio
import re
import wave
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

import speech_recognition as sr
from backend.config.settings import get_settings, Settings

logger = logging.getLogger("ai_voice_assistant.stt")

MIN_SPEECH_RMS_FOR_GEMINI_FALLBACK = 200.0


def _compute_wav_rms(audio_bytes: bytes) -> Optional[float]:
    """Compute 16-bit PCM RMS amplitude for WAV audio, or None if unparseable."""
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
            if wf.getsampwidth() != 2 or wf.getnframes() <= 0:
                return None
            frames = wf.readframes(wf.getnframes())
        samples = array.array("h", frames)
        if not samples:
            return 0.0
        step = max(1, len(samples) // 8000)
        sampled = samples[::step]
        return (sum(s * s for s in sampled) / len(sampled)) ** 0.5
    except Exception:
        return None


def _is_non_speech_transcript(text: str) -> bool:
    """Detect common silence hallucinations such as parenthetical tags or '00:00' timestamps."""
    clean = text.strip()
    if not clean:
        return True
    if clean.startswith("(") or "silence" in clean.lower():
        return True
    if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", clean):
        return True
    return False


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

        # Language candidate order
        candidates = ["en-IN", "en-US", "hi-IN"]
        if language in ("hi", "hindi"):
            candidates = ["hi-IN", "en-IN"]
        elif language in ("en-US", "en"):
            candidates = ["en-US", "en-IN"]

        def _recognize_one(audio_data: sr.AudioData, lang: str) -> str:
            rec = sr.Recognizer()
            rec.dynamic_energy_threshold = False
            rec.energy_threshold = 250
            try:
                text = rec.recognize_google(audio_data, language=lang)
                return text.strip() if text and text.strip() else ""
            except sr.UnknownValueError:
                return ""
            except Exception as err:
                logger.debug(f"Google STT ({lang}) error: {err}")
                return ""

        def _recognize() -> str:
            rec = sr.Recognizer()
            rec.dynamic_energy_threshold = False
            rec.energy_threshold = 250

            try:
                audio_file = io.BytesIO(audio_bytes)
                with sr.AudioFile(audio_file) as source:
                    audio_data = rec.record(source)

                if len(candidates) == 1:
                    return _recognize_one(audio_data, candidates[0])

                # Run primary + fallback language probes concurrently; return in preference order
                pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(candidates))
                try:
                    futures = [pool.submit(_recognize_one, audio_data, lang) for lang in candidates]
                    for lang, fut in zip(candidates, futures):
                        try:
                            text = fut.result(timeout=6.0)
                            if text:
                                logger.info(f"Google STT matched [{lang}]: '{text}'")
                                return text
                        except Exception:
                            continue
                finally:
                    for fut in locals().get("futures", []):
                        fut.cancel()
                    pool.shutdown(wait=False, cancel_futures=True)
                return ""
            except Exception as e:
                logger.warning(f"Google STT AudioFile decode error: {e}")
                return ""

        # Step 1: Try Google Speech Recognition
        transcript = ""
        try:
            transcript = await asyncio.to_thread(_recognize)
        except Exception as e:
            logger.warning(f"Async Google STT exception: {e}")

        if transcript and transcript.strip():
            return transcript.strip()

        # Step 2: Ultra-Reliable Fallback -> Gemini Multimodal Audio STT (skip if WAV is silence)
        rms = _compute_wav_rms(audio_bytes) if audio_format == "wav" else None
        if rms is not None and rms < MIN_SPEECH_RMS_FOR_GEMINI_FALLBACK:
            logger.info(f"Skipping Gemini STT fallback for quiet/silence clip (RMS={rms:.1f}).")
            return ""

        try:
            logger.info("Google STT returned empty -> Invoking Gemini Multimodal Audio fallback...")
            gemini_stt = GeminiMultimodalSTT()
            gem_transcript = await gemini_stt.transcribe(
                audio_bytes=audio_bytes,
                audio_format=audio_format,
                language=language,
            )
            if gem_transcript and not _is_non_speech_transcript(gem_transcript):
                clean_t = gem_transcript.strip()
                logger.info(f"Gemini Multimodal STT recovered transcript: '{clean_t}'")
                return clean_t
        except Exception as fallback_err:
            logger.warning(f"Gemini STT fallback failed: {fallback_err}")

        return ""


class GeminiMultimodalSTT(BaseSTTService):
    """STT implementation leveraging Gemini's native multimodal audio transcription."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._client = None
        self._last_key: str = ""

    def _get_client(self):
        from google import genai

        key = self.settings.gemini_api_key.strip()
        if self._client is None or self._last_key != key:
            self._client = genai.Client(api_key=key)
            self._last_key = key
        return self._client

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
            from google.genai import types

            client = self._get_client()
            mime = "audio/wav" if "wav" in audio_format else "audio/mp3"
            models_to_try = list(dict.fromkeys([
                self.settings.gemini_model,
                "gemini-flash-lite-latest",
                "gemini-3.5-flash",
                "gemini-3.1-flash-lite",
            ]))

            for m_name in models_to_try:
                try:
                    def _gemini_stt(target_model=m_name) -> str:
                        response = client.models.generate_content(
                            model=target_model,
                            contents=[
                                types.Part.from_bytes(data=audio_bytes, mime_type=mime),
                                (
                                    "Listen carefully to this audio and write down the exact speech verbatim. "
                                    "It could be in English, Hindi (हिन्दी), or Hinglish. "
                                    "If there is only silence or background noise with no clear speech, return an empty string. "
                                    "Return ONLY the transcribed text without quotes, timestamps, or explanations."
                                ),
                            ],
                            config=types.GenerateContentConfig(
                                max_output_tokens=120,
                                temperature=0.0,
                                http_options=types.HttpOptions(timeout=10000),
                            ),
                        )
                        if response and response.text:
                            return response.text.strip()
                        return ""

                    txt = await asyncio.wait_for(asyncio.to_thread(_gemini_stt), timeout=12.0)
                    return "" if _is_non_speech_transcript(txt) else txt
                except Exception as err:
                    logger.warning(f"Gemini STT attempt failed on {m_name}: {err}")
                    continue

            return ""
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
