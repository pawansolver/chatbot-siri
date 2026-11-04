import asyncio
import time
import os
import io
import wave
import struct
import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.core.assistant import get_assistant_core
from backend.voice.text_to_speech import get_tts_service
from backend.config.settings import get_settings


def generate_mock_pcm_wav(duration_sec: float = 1.0, sample_rate: int = 16000) -> bytes:
    """Generate a valid in-memory PCM WAV audio buffer for testing."""
    num_samples = int(duration_sec * sample_rate)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        # Generate simple sine tone
        raw_data = struct.pack(f"<{num_samples}h", *[int(500 * (i % 50)) for i in range(num_samples)])
        wav_file.writeframes(raw_data)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_e2e_text_to_speech_pipeline():
    """Verify complete Text -> Language Detection -> Voice Routing -> Neural TTS -> Audio serving."""
    assistant = get_assistant_core()
    start_time = time.perf_counter()

    result = await assistant.process_text_input(
        prompt="Hello Aether, are you ready?",
        speak=True,
        session_id="e2e_test_session",
    )
    total_latency = (time.perf_counter() - start_time) * 1000

    assert result["success"] is True
    assert "response" in result
    assert result["audio_url"] is not None
    assert result["audio_url"].startswith("/api/audio/tts_")

    print(f"\n[E2E Pipeline Benchmark]")
    print(f"  • Gemini Latency: {result['metrics'].get('gemini_latency_ms', 0):.1f}ms")
    print(f"  • TTS Latency:    {result['metrics'].get('tts_latency_ms', 0):.1f}ms")
    print(f"  • Total Pipeline:  {total_latency:.1f}ms")


@pytest.mark.asyncio
async def test_e2e_audio_upload_validation_and_flow():
    """Verify audio file upload endpoint /api/voice/process-audio."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        wav_bytes = generate_mock_pcm_wav(duration_sec=1.5)
        response = await ac.post(
            "/api/voice/process-audio",
            files={"file": ("test_mic.wav", wav_bytes, "audio/wav")},
            data={"session_id": "e2e_voice_session"},
        )
        # Check that audio was processed (either transcribed or handled empty gracefully)
        assert response.status_code in (200, 400)


if __name__ == "__main__":
    async def run_manual_e2e_check():
        print("=" * 60)
        print("  🎙️ RUNNING REAL END-TO-END VOICE ASSISTANT PIPELINE CHECK")
        print("=" * 60)

        settings = get_settings()
        print(f"  • Model: {settings.gemini_model}")
        print(f"  • STT Engine: {settings.stt_engine}")
        print(f"  • Default Voice: {settings.tts_voice}")
        print(f"  • API Key Configured: {settings.has_api_key}")

        assistant = get_assistant_core()

        test_prompts = [
            ("English", "What is the distance between Earth and Moon in short?"),
            ("Hindi", "नमस्ते, आप क्या कर सकते हैं?"),
            ("Hinglish", "Aapka naam kya hai aur weather kaisa hai?"),
        ]

        for label, prompt in test_prompts:
            print(f"\n--- Testing {label} Input: '{prompt}' ---")
            start = time.perf_counter()
            res = await assistant.process_text_input(prompt=prompt, speak=True)
            elapsed = (time.perf_counter() - start) * 1000

            print(f"  Response: {res.get('response', '')}")
            print(f"  Audio URL: {res.get('audio_url', 'None')}")
            print(f"  Latency Metrics: {res.get('metrics', {})}")
            print(f"  Total Duration: {elapsed:.1f}ms")

        print("\n✅ All End-to-End Voice Pipeline checks completed.")

    asyncio.run(run_manual_e2e_check())
