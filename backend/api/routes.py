import os
import re
import time
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, Request, status
from fastapi.responses import FileResponse, JSONResponse

from backend.config.settings import Settings, get_settings
from backend.core.assistant import AssistantCore, get_assistant_core
from backend.core.state_manager import StateManager, AssistantState, get_state_manager
from backend.core.session import SessionManager, get_session_manager
from backend.core.device_state import DeviceStateManager, DeviceState, get_device_state_manager
from backend.voice.speech_to_text import BaseSTTService, get_stt_service
from backend.voice.text_to_speech import TextToSpeechService, get_tts_service, TEMP_AUDIO_DIR
from backend.api.schemas import (
    ChatRequest,
    ChatResponse,
    AudioProcessResponse,
    ConfigUpdateRequest,
    ConfigResponse,
    TTSRequest,
    ResetStateRequest,
    HealthResponse,
    DeviceStateResponse,
)

logger = logging.getLogger("ai_voice_assistant.api")

router = APIRouter(tags=["Assistant API"])


# -----------------------------------------------------------------------------
# Health Check & Device Status Endpoints
# -----------------------------------------------------------------------------
@router.get("/health/live", response_model=HealthResponse, tags=["Health"])
async def health_liveness():
    """Liveness probe: verifies the process is running and responsive."""
    return HealthResponse(status="alive", ready=True)


@router.get("/health/ready", response_model=HealthResponse, tags=["Health"])
async def health_readiness(
    settings: Settings = Depends(get_settings),
    assistant: AssistantCore = Depends(get_assistant_core),
    device_mgr: DeviceStateManager = Depends(get_device_state_manager),
):
    """Readiness probe: verifies sub-services and physical hardware state."""
    status_info = await assistant.get_status()
    is_ready = bool(status_info.get("state") != "ERROR" and device_mgr.current_state != DeviceState.ERROR)
    return HealthResponse(
        status="ready" if is_ready else "degraded",
        ready=is_ready,
        details={
            "gemini_connected": status_info.get("gemini", {}).get("status") == "connected",
            "has_api_key": settings.has_api_key,
            "device_state": device_mgr.current_state.value,
            "stt_engine": settings.stt_engine,
            "tts_voice": settings.tts_voice,
        },
    )


@router.get("/api/device/state", response_model=DeviceStateResponse, tags=["Device Hardware"])
async def get_device_state(device_mgr: DeviceStateManager = Depends(get_device_state_manager)):
    """Retrieve physical hardware device status and telemetry."""
    return DeviceStateResponse(
        device_state=device_mgr.current_state.value,
        telemetry=device_mgr.telemetry,
    )


@router.post("/api/device/state", response_model=DeviceStateResponse, tags=["Device Hardware"])
async def set_device_state(
    target_state: str,
    device_mgr: DeviceStateManager = Depends(get_device_state_manager),
):
    """Update physical hardware device status (e.g. READY, OFFLINE, BOOTING)."""
    target = target_state.upper().strip()
    if target in DeviceState.__members__:
        device_mgr.set_device_state(DeviceState[target])
    else:
        raise HTTPException(status_code=400, detail=f"Invalid device state: {target_state}")
    return DeviceStateResponse(
        device_state=device_mgr.current_state.value,
        telemetry=device_mgr.telemetry,
    )


# -----------------------------------------------------------------------------
# Assistant Core REST Endpoints
# -----------------------------------------------------------------------------
@router.get("/api/status")
async def get_status(
    assistant: AssistantCore = Depends(get_assistant_core),
    device_mgr: DeviceStateManager = Depends(get_device_state_manager),
):
    """Check API connectivity, conversational state, active model, and physical device state."""
    status_data = await assistant.get_status()
    status_data["device_state"] = device_mgr.current_state.value
    return status_data


@router.get("/api/config", response_model=ConfigResponse)
async def get_config(settings: Settings = Depends(get_settings)):
    """Return runtime configurable options: models, languages, voices, and STT engines."""
    return ConfigResponse(**settings.get_safe_dict())


@router.post("/api/config", response_model=ConfigResponse)
async def update_config(
    payload: ConfigUpdateRequest,
    settings: Settings = Depends(get_settings),
):
    """Update runtime configuration settings."""
    if payload.gemini_model:
        settings.gemini_model = payload.gemini_model
    if payload.stt_engine:
        settings.stt_engine = payload.stt_engine
    if payload.language_mode:
        settings.language_mode = payload.language_mode
    if payload.tts_voice:
        settings.tts_voice = payload.tts_voice

    logger.info(
        f"Configuration updated: Model={settings.gemini_model}, STT={settings.stt_engine}, Lang={settings.language_mode}"
    )
    return ConfigResponse(**settings.get_safe_dict())


@router.post("/api/chat", response_model=ChatResponse)
async def chat_message(
    payload: ChatRequest,
    request: Request,
    assistant: AssistantCore = Depends(get_assistant_core),
):
    """Send text prompt -> Command Router -> Gemini AI -> Neural TTS with Generation ID."""
    trace_id = getattr(request.state, "trace_id", "local_req")
    result = await assistant.process_text_input(
        prompt=payload.message,
        speak=payload.speak,
        source="text",
        session_id=payload.session_id,
        model_override=payload.model,
        language_override=payload.language,
        trace_id=trace_id,
    )
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Failed to process chat message"),
        )
    return ChatResponse(**result)


@router.post("/api/voice/process-audio", response_model=AudioProcessResponse)
async def process_audio_file(
    request: Request,
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(default=None),
    assistant: AssistantCore = Depends(get_assistant_core),
):
    """Upload recorded voice audio -> STT -> Command Router -> Gemini AI -> Neural TTS."""
    trace_id = getattr(request.state, "trace_id", "local_req")
    try:
        audio_bytes = await file.read()
        if not audio_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty audio file provided.",
            )

        with open(r"C:\ProductSpeaker\backend\temp_audio\last_incoming_audio.wav", "wb") as f_in:
            f_in.write(audio_bytes)


        filename = file.filename or "audio.wav"
        fmt = "webm" if "webm" in filename.lower() else "wav"

        result = await assistant.process_audio_input(
            audio_bytes=audio_bytes,
            audio_format=fmt,
            session_id=session_id,
            trace_id=trace_id,
        )
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("error", "Failed to process audio"),
            )
        return AudioProcessResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in process_audio_file: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/api/voice/stt")
async def speech_to_text(
    file: UploadFile = File(...),
    language: Optional[str] = Form(default="auto"),
    stt_svc: BaseSTTService = Depends(get_stt_service),
):
    """Transcribe an uploaded audio file into text using configured STT engine."""
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    transcript = await stt_svc.transcribe(audio_bytes=audio_bytes, language=language or "auto")
    return {"transcript": transcript}


@router.post("/api/voice/tts")
async def text_to_speech(
    payload: TTSRequest,
    tts_svc: TextToSpeechService = Depends(get_tts_service),
):
    """Synthesize text into speech audio and return URL."""
    audio_filename = await tts_svc.synthesize_to_file(payload.text, voice=payload.voice)
    if not audio_filename:
        raise HTTPException(status_code=500, detail="Failed to synthesize speech audio.")

    return {
        "success": True,
        "filename": audio_filename,
        "audio_url": f"/api/audio/{audio_filename}",
    }


@router.get("/api/history")
async def get_history(
    session_id: Optional[str] = None,
    session_mgr: SessionManager = Depends(get_session_manager),
):
    """Retrieve conversation history for a specific session."""
    session = session_mgr.get_or_create_session(session_id)
    return {
        "session_id": session.session_id,
        "generation_id": session.active_generation_id,
        "history": session.conversation.get_history(),
    }


@router.delete("/api/history")
async def clear_history(
    session_id: Optional[str] = None,
    session_mgr: SessionManager = Depends(get_session_manager),
):
    """Clear conversation history for a specific session."""
    session = session_mgr.get_or_create_session(session_id)
    session.conversation.clear()
    return {
        "success": True,
        "session_id": session.session_id,
        "message": "Conversation history cleared.",
    }


@router.post("/api/state/reset")
async def reset_state(
    payload: ResetStateRequest = ResetStateRequest(),
    state_mgr: StateManager = Depends(get_state_manager),
    session_mgr: SessionManager = Depends(get_session_manager),
):
    """Reset assistant state or trigger barge-in cancellation for current generation."""
    if payload.barge_in:
        state_mgr.cancel_active_task()
        if payload.session_id:
            session = session_mgr.get_session(payload.session_id)
            if session:
                session.cancel_current_generation()
    else:
        target = payload.state.upper() if payload.state else "IDLE"
        if target in AssistantState.__members__:
            state_mgr.set_state(AssistantState[target])
        else:
            state_mgr.reset_to_idle()
    return {"state": state_mgr.current_state.value}


@router.get("/api/audio/{filename}")
async def get_audio_file(filename: str):
    """Serve synthesized temporary audio file with path sanitization."""
    safe_name = os.path.basename(filename)
    if not re.match(r"^tts_[a-zA-Z0-9_-]+\.(mp3|wav)$", safe_name):
        raise HTTPException(status_code=400, detail="Invalid audio filename")

    file_path = TEMP_AUDIO_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found or expired")

    media_type = "audio/wav" if safe_name.endswith(".wav") else "audio/mpeg"
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=safe_name,
        headers={"Cache-Control": "no-cache"},
    )
