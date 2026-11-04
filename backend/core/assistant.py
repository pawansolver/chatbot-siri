import time
import asyncio
import logging
from typing import Dict, Any, Optional

from backend.config.settings import get_settings, Settings
from backend.core.state_manager import StateManager, AssistantState, get_state_manager
from backend.core.session import SessionManager, get_session_manager
from backend.core.memory import BaseMemoryStore, get_memory_store
from backend.core.command_router import CommandRouter, get_command_router
from backend.ai.gemini_service import GeminiService, get_gemini_service
from backend.voice.speech_to_text import BaseSTTService, get_stt_service
from backend.voice.text_to_speech import TextToSpeechService, get_tts_service
from backend.voice.language_detector import LanguageDetector, get_language_detector
from backend.voice.voice_router import VoiceRouter, get_voice_router
from backend.voice.audio_normalizer import AudioNormalizer, get_audio_normalizer
from backend.middleware.observability import log_pipeline_metrics

logger = logging.getLogger("ai_voice_assistant.core")


class AssistantCore:
    """Central AI assistant coordinator orchestrating STT -> Command Routing -> Language Routing -> Gemini -> Neural TTS."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        state_mgr: Optional[StateManager] = None,
        session_mgr: Optional[SessionManager] = None,
        command_router: Optional[CommandRouter] = None,
        memory_store: Optional[BaseMemoryStore] = None,
        gemini_svc: Optional[GeminiService] = None,
        stt_svc: Optional[BaseSTTService] = None,
        tts_svc: Optional[TextToSpeechService] = None,
        lang_detector: Optional[LanguageDetector] = None,
        voice_router: Optional[VoiceRouter] = None,
        audio_normalizer: Optional[AudioNormalizer] = None,
    ):
        self.settings = settings or get_settings()
        self.state_mgr = state_mgr or get_state_manager()
        self.session_mgr = session_mgr or get_session_manager()
        self.command_router = command_router or get_command_router()
        self.memory_store = memory_store or get_memory_store()
        self.gemini_svc = gemini_svc or get_gemini_service()
        self.stt_svc = stt_svc or get_stt_service()
        self.tts_svc = tts_svc or get_tts_service()
        self.lang_detector = lang_detector or get_language_detector()
        self.voice_router = voice_router or get_voice_router()
        self.audio_normalizer = audio_normalizer or get_audio_normalizer()

    async def get_status(self) -> Dict[str, Any]:
        """Return system health, state, and connectivity."""
        gemini_conn = await self.gemini_svc.verify_connection()
        return {
            "state": self.state_mgr.current_state.value,
            "has_api_key": self.settings.has_api_key,
            "gemini": gemini_conn,
            "model": self.settings.gemini_model,
            "voice": self.settings.tts_voice,
            "stt_engine": self.settings.stt_engine,
            "language_mode": self.settings.language_mode,
        }

    async def process_text_input(
        self,
        prompt: str,
        speak: bool = True,
        source: str = "text",
        session_id: Optional[str] = None,
        model_override: Optional[str] = None,
        language_override: Optional[str] = None,
        trace_id: str = "local_trace",
    ) -> Dict[str, Any]:
        """Process text prompt through Command Router -> Gemini AI -> Neural TTS with Generation ID validation."""
        total_start = time.perf_counter()
        clean_prompt = prompt.strip()

        if not clean_prompt:
            return {
                "success": False,
                "error": "Empty prompt provided.",
                "state": self.state_mgr.current_state.value,
                "trace_id": trace_id,
            }

        # Check payload length
        if len(clean_prompt) > self.settings.max_message_length:
            return {
                "success": False,
                "error": f"Message exceeds maximum allowed limit ({self.settings.max_message_length} characters).",
                "state": self.state_mgr.current_state.value,
                "trace_id": trace_id,
            }

        session = self.session_mgr.get_or_create_session(session_id)
        current_sid = session.session_id

        # ---------------------------------------------------------------------
        # 1. Local Command Router Evaluation (Bypasses Gemini if command matched)
        # ---------------------------------------------------------------------
        cmd_result = self.command_router.route(clean_prompt, preferred_lang=self.settings.language_mode)
        if cmd_result.is_command:
            logger.info(f"[{trace_id}] Executing local command: {cmd_result.command_name}")
            
            # If command is Stop / Cancel -> abort active task
            if cmd_result.action in ("STOP_PLAYBACK", "CANCEL"):
                self.state_mgr.cancel_active_task()
                session.cancel_current_generation()
            elif cmd_result.action == "CLEAR_HISTORY":
                session.conversation.clear()

            audio_filename = None
            audio_url = None
            if speak and cmd_result.response_text:
                chosen_voice = self.voice_router.route_voice(cmd_result.response_text)
                audio_filename = await self.tts_svc.synthesize_to_file(cmd_result.response_text, voice=chosen_voice)
                if audio_filename:
                    audio_url = f"/api/audio/{audio_filename}"

            return {
                "success": True,
                "is_command": True,
                "command_name": cmd_result.command_name,
                "action": cmd_result.action,
                "prompt": clean_prompt,
                "response": cmd_result.response_text or "",
                "audio_filename": audio_filename,
                "audio_url": audio_url,
                "session_id": current_sid,
                "generation_id": session.active_generation_id,
                "trace_id": trace_id,
                "metrics": {"total_duration_ms": round((time.perf_counter() - total_start) * 1000, 1)},
                "state": self.state_mgr.current_state.value,
            }

        # ---------------------------------------------------------------------
        # 2. Start New Generation & Invalidate Previous Generation
        # ---------------------------------------------------------------------
        generation_id = session.new_generation()

        # If assistant was speaking, handle barge-in cancellation of prior task
        if self.state_mgr.current_state == AssistantState.SPEAKING:
            self.state_mgr.cancel_active_task()

        gemini_ms = 0.0
        tts_ms = 0.0

        async with self.state_mgr.acquire_lock():
            current_task = asyncio.current_task()
            if current_task:
                self.state_mgr.set_active_task(current_task)

            try:
                # State: THINKING
                self.state_mgr.set_state(AssistantState.THINKING)

                # Validate generation has not been superseded
                if not session.is_current_generation(generation_id):
                    logger.warning(f"[{trace_id}] Generation {generation_id} superseded before LLM call. Discarding.")
                    return {
                        "success": False,
                        "error": "Request cancelled / superseded by a newer generation.",
                        "generation_id": generation_id,
                        "state": self.state_mgr.current_state.value,
                        "session_id": current_sid,
                        "trace_id": trace_id,
                    }

                # Fetch isolated session history
                history_context = session.conversation.get_gemini_context()
                user_msg = session.conversation.add_user_message(clean_prompt, source=source)

                # Query Gemini AI
                response_text, gemini_ms = await self.gemini_svc.generate_response(
                    prompt=clean_prompt,
                    history=history_context,
                )

                # Validate generation has not been superseded during Gemini call
                if not session.is_current_generation(generation_id):
                    logger.warning(f"[{trace_id}] Generation {generation_id} superseded during LLM generation. Discarding.")
                    return {
                        "success": False,
                        "error": "Response superseded by newer generation.",
                        "generation_id": generation_id,
                        "state": self.state_mgr.current_state.value,
                        "session_id": current_sid,
                        "trace_id": trace_id,
                    }

                assistant_msg = session.conversation.add_assistant_message(response_text)

                audio_filename: Optional[str] = None
                audio_url: Optional[str] = None
                chosen_voice = self.settings.tts_voice

                # 3. Dynamic Voice Routing & Neural TTS
                if speak and response_text:
                    self.state_mgr.set_state(AssistantState.SPEAKING)
                    tts_start = time.perf_counter()

                    chosen_voice = self.voice_router.route_voice(response_text)
                    audio_filename = await self.tts_svc.synthesize_to_file(
                        text=response_text,
                        voice=chosen_voice,
                    )
                    tts_ms = (time.perf_counter() - tts_start) * 1000

                    # Validate generation after TTS synthesis
                    if not session.is_current_generation(generation_id):
                        logger.warning(f"[{trace_id}] Generation {generation_id} superseded after TTS. Discarding audio.")
                        return {
                            "success": False,
                            "error": "Audio superseded by newer generation.",
                            "generation_id": generation_id,
                            "state": self.state_mgr.current_state.value,
                            "session_id": current_sid,
                            "trace_id": trace_id,
                        }

                    if audio_filename:
                        audio_url = f"/api/audio/{audio_filename}"

                total_ms = (time.perf_counter() - total_start) * 1000

                log_pipeline_metrics(
                    trace_id=trace_id,
                    session_id=current_sid,
                    stt_duration_ms=0.0,
                    gemini_latency_ms=gemini_ms,
                    tts_latency_ms=tts_ms,
                    total_duration_ms=total_ms,
                    model=model_override or self.settings.gemini_model,
                    voice=chosen_voice,
                    language=self.lang_detector.detect(clean_prompt).value,
                    state=self.state_mgr.current_state.value,
                )

                return {
                    "success": True,
                    "prompt": clean_prompt,
                    "user_message_id": user_msg.id,
                    "response": response_text,
                    "assistant_message_id": assistant_msg.id,
                    "audio_filename": audio_filename,
                    "audio_url": audio_url,
                    "session_id": current_sid,
                    "generation_id": generation_id,
                    "trace_id": trace_id,
                    "metrics": {
                        "gemini_latency_ms": round(gemini_ms, 1),
                        "tts_latency_ms": round(tts_ms, 1),
                        "total_duration_ms": round(total_ms, 1),
                    },
                    "state": self.state_mgr.current_state.value,
                }
            except asyncio.CancelledError:
                logger.info(f"[{trace_id}] Request cancelled due to user barge-in / cancellation.")
                session.cancel_current_generation()
                self.state_mgr.reset_to_idle()
                return {
                    "success": False,
                    "error": "Request cancelled by user barge-in.",
                    "state": AssistantState.IDLE.value,
                    "session_id": current_sid,
                    "generation_id": generation_id,
                    "trace_id": trace_id,
                }
            except Exception as e:
                logger.error(f"Error in process_text_input: {e}", exc_info=True)
                self.state_mgr.reset_to_idle()
                return {
                    "success": False,
                    "error": f"An error occurred: {str(e)}",
                    "state": AssistantState.IDLE.value,
                    "session_id": current_sid,
                    "generation_id": generation_id,
                    "trace_id": trace_id,
                }
            finally:
                self.state_mgr.reset_to_idle()

    async def process_audio_input(
        self,
        audio_bytes: bytes,
        audio_format: str = "wav",
        session_id: Optional[str] = None,
        trace_id: str = "local_trace",
    ) -> Dict[str, Any]:
        """Process raw microphone audio through STT -> Command Routing -> Gemini -> TTS with Generation ID validation."""
        total_start = time.perf_counter()

        is_valid, err_msg = self.audio_normalizer.validate_audio(
            audio_bytes,
            max_size_bytes=self.settings.max_audio_size_bytes,
        )
        if not is_valid:
            return {
                "success": False,
                "error": err_msg or "Invalid audio received.",
                "state": self.state_mgr.current_state.value,
                "trace_id": trace_id,
            }

        session = self.session_mgr.get_or_create_session(session_id)
        current_sid = session.session_id

        # Start new generation for this voice interaction
        generation_id = session.new_generation()

        if self.state_mgr.current_state == AssistantState.SPEAKING:
            self.state_mgr.cancel_active_task()

        transcript = ""
        stt_ms = 0.0

        async with self.state_mgr.acquire_lock():
            current_task = asyncio.current_task()
            if current_task:
                self.state_mgr.set_active_task(current_task)

            try:
                # State: LISTENING
                self.state_mgr.set_state(AssistantState.LISTENING)
                stt_start = time.perf_counter()

                normalized_bytes, fmt = self.audio_normalizer.normalize_to_wav(audio_bytes)
                transcript = await self.stt_svc.transcribe(
                    audio_bytes=normalized_bytes,
                    audio_format=fmt,
                    language=self.settings.language_mode,
                )
                stt_ms = (time.perf_counter() - stt_start) * 1000
                logger.info(f"STT transcription finished in {stt_ms:.1f}ms: '{transcript}'")

                if not transcript or not transcript.strip():
                    logger.info("Unintelligible audio: synthesizing gentle vocal prompt.")
                    fallback_text = "I didn't catch that. Please say that again."
                    tts_file = await self.tts_svc.synthesize_to_file(text=fallback_text, voice=self.settings.tts_voice_en)
                    audio_url = f"/api/audio/{tts_file}" if tts_file else None
                    self.state_mgr.reset_to_idle()
                    return {
                        "success": True,
                        "prompt": "(unintelligible)",
                        "response": fallback_text,
                        "audio_filename": tts_file,
                        "audio_url": audio_url,
                        "session_id": current_sid,
                        "generation_id": generation_id,
                        "trace_id": trace_id,
                        "state": AssistantState.IDLE.value,
                    }

                # Check if generation was cancelled during STT
                if not session.is_current_generation(generation_id):
                    logger.warning(f"[{trace_id}] Voice generation {generation_id} superseded during STT.")
                    return {
                        "success": False,
                        "error": "Voice request superseded.",
                        "session_id": current_sid,
                        "generation_id": generation_id,
                        "trace_id": trace_id,
                    }
            except asyncio.CancelledError:
                logger.info(f"[{trace_id}] Audio processing cancelled by user barge-in.")
                session.cancel_current_generation()
                self.state_mgr.reset_to_idle()
                return {
                    "success": False,
                    "error": "Audio processing cancelled.",
                    "state": AssistantState.IDLE.value,
                    "session_id": current_sid,
                    "generation_id": generation_id,
                    "trace_id": trace_id,
                }
            except Exception as e:
                logger.error(f"Error processing audio input: {e}", exc_info=True)
                self.state_mgr.reset_to_idle()
                return {
                    "success": False,
                    "error": str(e),
                    "state": AssistantState.IDLE.value,
                    "session_id": current_sid,
                    "generation_id": generation_id,
                    "trace_id": trace_id,
                }
            finally:
                self.state_mgr.reset_to_idle()

        # Route transcript through process_text_input cleanly outside of STT lock
        return await self.process_text_input(
            prompt=transcript,
            speak=True,
            source="voice",
            session_id=current_sid,
            trace_id=trace_id,
        )


_assistant_core_instance: Optional[AssistantCore] = None


def get_assistant_core() -> AssistantCore:
    """Singleton getter for AssistantCore."""
    global _assistant_core_instance
    if _assistant_core_instance is None:
        _assistant_core_instance = AssistantCore()
    return _assistant_core_instance
