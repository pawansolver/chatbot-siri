import asyncio
import pytest
from backend.config.settings import Settings
from backend.ai.gemini_service import GeminiService


@pytest.mark.asyncio
async def test_gemini_missing_key():
    """Verify GeminiService handles missing API key gracefully."""
    settings = Settings(gemini_api_key="")
    service = GeminiService(settings=settings)

    # Check connection check
    status = await service.verify_connection()
    assert status["status"] == "missing_key"

    # Check response generation
    response, latency_ms = await service.generate_response("Hello")
    assert "Gemini API Key is missing" in response


@pytest.mark.asyncio
async def test_gemini_empty_prompt():
    """Verify GeminiService handles empty prompt gracefully."""
    settings = Settings(gemini_api_key="mock_key")
    service = GeminiService(settings=settings)

    response, latency_ms = await service.generate_response("")
    assert "didn't catch that" in response


@pytest.mark.asyncio
async def test_gemini_streaming_generator():
    """Verify GeminiService streaming generator produces stream chunks."""
    settings = Settings(gemini_api_key="")
    service = GeminiService(settings=settings)

    chunks = []
    async for chunk in service.generate_response_stream("Hello"):
        chunks.append(chunk)

    assert len(chunks) > 0
    full_text = "".join(chunks)
    assert "Gemini API Key is missing" in full_text
