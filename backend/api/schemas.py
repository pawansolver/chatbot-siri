import time
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1500, description="User prompt message")
    speak: bool = Field(default=True, description="Whether to generate TTS audio response")
    session_id: Optional[str] = Field(default=None, description="Client session ID")
    generation_id: Optional[str] = Field(default=None, description="Optional generation ID from client")
    model: Optional[str] = Field(default=None, description="Optional custom Gemini model override")
    language: Optional[str] = Field(default=None, description="Optional language mode override")


class ChatResponse(BaseModel):
    success: bool
    prompt: str
    response: str
    audio_url: Optional[str] = None
    session_id: str
    generation_id: str
    trace_id: str
    is_command: bool = False
    command_name: Optional[str] = None
    action: Optional[str] = None
    metrics: Dict[str, float] = Field(default_factory=dict)
    state: str = "IDLE"
    error: Optional[str] = None


class AudioProcessResponse(BaseModel):
    success: bool
    transcript: str = ""
    prompt: str = ""
    response: str = ""
    audio_url: Optional[str] = None
    session_id: str
    generation_id: str
    trace_id: str
    is_command: bool = False
    command_name: Optional[str] = None
    action: Optional[str] = None
    metrics: Dict[str, float] = Field(default_factory=dict)
    state: str = "IDLE"
    error: Optional[str] = None


class ConfigUpdateRequest(BaseModel):
    gemini_model: Optional[str] = Field(default=None, description="Configured Gemini model")
    stt_engine: Optional[str] = Field(default=None, description="STT provider engine")
    language_mode: Optional[str] = Field(default=None, description="Language mode (auto/en/hi/hinglish)")
    tts_voice: Optional[str] = Field(default=None, description="Neural voice")


class ConfigResponse(BaseModel):
    active_model: str
    available_models: List[str]
    active_stt_engine: str
    available_stt_engines: List[str]
    active_language_mode: str
    available_languages: List[str]
    active_voice: str
    rate_limit_per_minute: int
    max_message_length: int
    max_history_turns: int


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Text to synthesize to speech")
    voice: Optional[str] = Field(default=None, description="Optional custom neural voice")


class ResetStateRequest(BaseModel):
    state: Optional[str] = Field(default="IDLE", description="Target state to set")
    barge_in: bool = Field(default=False, description="Whether this reset is an active user barge-in interrupt")
    session_id: Optional[str] = Field(default=None, description="Session ID")
    generation_id: Optional[str] = Field(default=None, description="Generation ID to invalidate")


class HealthResponse(BaseModel):
    status: str
    timestamp: float = Field(default_factory=time.time)
    service: str = "ai_voice_assistant"
    version: str = "1.0.0"
    ready: bool = True
    details: Dict[str, Any] = Field(default_factory=dict)


class DeviceStateResponse(BaseModel):
    device_state: str
    telemetry: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class WebSocketEvent(BaseModel):
    type: str  # "state_change" | "device_state_change" | "stream_chunk" | "final_response" | "command_executed" | "cancel_generation" | "error"
    state: Optional[str] = None
    generation_id: Optional[str] = None
    session_id: Optional[str] = None
    data: Any = None
    timestamp: float = Field(default_factory=time.time)
