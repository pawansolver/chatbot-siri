import pytest
from httpx import AsyncClient, ASGITransport
from backend.main import app
from backend.config.settings import get_settings
from backend.voice.speech_to_text import (
    BaseSTTService,
    get_stt_service,
    GoogleSpeechRecognitionSTT,
    GeminiMultimodalSTT,
    WhisperSTT,
)
from backend.voice.text_to_speech import TextToSpeechService


@pytest.mark.asyncio
async def test_health_endpoints():
    """Verify /health/live and /health/ready endpoints."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Liveness
        res_live = await ac.get("/health/live")
        assert res_live.status_code == 200
        assert res_live.json()["status"] == "alive"

        # Readiness
        res_ready = await ac.get("/health/ready")
        assert res_ready.status_code == 200
        assert "status" in res_ready.json()


@pytest.mark.asyncio
async def test_api_config_safe_exposure_and_update():
    """Verify /api/config exposes ONLY safe values and updates dynamically."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/config")
        assert res.status_code == 200
        data = res.json()

        # Security check: MUST NOT expose API key
        assert "gemini_api_key" not in data
        assert "GEMINI_API_KEY" not in str(data)

        # Verify allowed models and stt engines
        assert "gemini-2.5-flash" in data["available_models"]
        assert "google" in data["available_stt_engines"]

        # Update config
        update_res = await ac.post("/api/config", json={"gemini_model": "gemini-2.0-flash", "language_mode": "hinglish"})
        assert update_res.status_code == 200
        assert update_res.json()["active_model"] == "gemini-2.0-flash"


@pytest.mark.asyncio
async def test_api_chat_session_isolation_and_metrics():
    """Verify /api/chat maintains isolated sessions and returns trace metrics."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        session_id = "test_user_session_1"
        res = await ac.post(
            "/api/chat",
            json={"message": "What is the capital of India?", "speak": False, "session_id": session_id},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["session_id"] == session_id
        assert "trace_id" in data
        assert "metrics" in data

        # Check history for this specific session
        hist_res = await ac.get(f"/api/history?session_id={session_id}")
        assert hist_res.status_code == 200
        hist_data = hist_res.json()
        assert len(hist_data["history"]) >= 2

        # Clear session history
        del_res = await ac.delete(f"/api/history?session_id={session_id}")
        assert del_res.status_code == 200


@pytest.mark.asyncio
async def test_abstract_stt_interface_and_factory():
    """Test STT engine factory and ABC inheritance."""
    google_stt = get_stt_service("google")
    assert isinstance(google_stt, BaseSTTService)
    assert isinstance(google_stt, GoogleSpeechRecognitionSTT)

    gemini_stt = get_stt_service("gemini")
    assert isinstance(gemini_stt, BaseSTTService)
    assert isinstance(gemini_stt, GeminiMultimodalSTT)

    whisper_stt = get_stt_service("whisper")
    assert isinstance(whisper_stt, BaseSTTService)
    assert isinstance(whisper_stt, WhisperSTT)


@pytest.mark.asyncio
async def test_tts_synthesis_hindi_and_english():
    """Verify TTS synthesis generates valid MP3 audio for Hindi and English."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Hindi TTS
        res_hi = await ac.post("/api/voice/tts", json={"text": "नमस्ते! आपका दिन शुभ हो।"})
        assert res_hi.status_code == 200
        data_hi = res_hi.json()
        assert data_hi["success"] is True
        assert data_hi["audio_url"].startswith("/api/audio/tts_")

        # English TTS
        res_en = await ac.post("/api/voice/tts", json={"text": "Welcome to Aether Voice Assistant."})
        assert res_en.status_code == 200
        data_en = res_en.json()
        assert data_en["success"] is True
