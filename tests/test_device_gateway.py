"""Tests for ProductSpeaker thin Device Gateway, per-device pairing, and Diffy Agent API forwarding."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.config.settings import Settings
from backend.core.assistant import AssistantCore
from backend.main import create_app


@pytest.mark.asyncio
async def test_assistant_core_forwards_to_diffy_agent_gateway():
    """Verify AssistantCore in Device Gateway mode calls Diffy Agent API instead of local Gemini."""
    settings = Settings(use_agent_gateway=True, diffy_agent_api_url="http://127.0.0.1:3001")
    mock_agent = AsyncMock()
    mock_agent.chat_completion.return_value = ("Main samajh sakta hoon, aap shant rahein.", 18.4)
    mock_tts = AsyncMock()
    mock_tts.synthesize_to_file.return_value = "tts_test.mp3"

    core = AssistantCore(settings=settings, agent_client=mock_agent, tts_svc=mock_tts)
    res = await core.process_text_input(
        prompt="Ghar mein bahut tension hai",
        speak=True,
        session_id="esp32_test_1",
        device_token="fluai_dev_sample123",
    )

    assert res["success"] is True
    assert "samajh" in res["response"]
    assert res["audio_url"] == "/api/audio/tts_test.mp3"
    mock_agent.chat_completion.assert_awaited_once()
    call_kwargs = mock_agent.chat_completion.call_args.kwargs
    assert call_kwargs["device_token"] == "fluai_dev_sample123"


def test_device_pair_endpoint_and_token_auth():
    """Verify /api/device/pair issues per-device token and auth accepts paired fluai_dev_ tokens."""
    app = create_app()
    client = TestClient(app)

    fake_pair = {
        "status": "paired",
        "device_id": "esp32_aa_bb",
        "user_id": "user_canonical_42",
        "device_name": "Living Room",
        "device_token": "fluai_dev_valid_token_999",
    }

    with patch("backend.api.routes.get_agent_gateway_client") as mock_get_gw:
        mock_gw = AsyncMock()
        mock_gw.pair_device.return_value = fake_pair
        mock_get_gw.return_value = mock_gw

        r = client.post(
            "/api/device/pair",
            json={"device_id": "esp32_aa_bb", "user_id": "user_canonical_42", "device_name": "Living Room"},
        )
        assert r.status_code == 200
        assert r.json()["device_token"] == "fluai_dev_valid_token_999"

    with patch("backend.middleware.auth.get_agent_gateway_client") as mock_auth_gw:
        gw = AsyncMock()
        gw.resolve_device_token.return_value = {"device_id": "esp32_aa_bb", "user_id": "user_canonical_42"}
        mock_auth_gw.return_value = gw

        res = client.get("/api/config", headers={"X-Device-Token": "fluai_dev_valid_token_999"})
        assert res.status_code == 200

        gw.resolve_device_token.return_value = None
        bad = client.get("/api/config", headers={"X-Device-Token": "fluai_dev_invalid"})
        assert bad.status_code == 401


def test_websocket_stream_chat_routes_through_agent_gateway():
    """Verify /api/ws stream_chat uses AgentGatewayClient without crashing when gemini_svc is None."""
    settings = Settings(use_agent_gateway=True, diffy_agent_api_url="http://127.0.0.1:3001")
    mock_agent = AsyncMock()
    mock_agent.chat_completion.return_value = ("Diffy gateway reply over WS.", 12.0)
    core = AssistantCore(settings=settings, agent_client=mock_agent)
    assert core.gemini_svc is None

    app = create_app()
    client = TestClient(app)

    with patch("backend.api.websocket.get_assistant_core", return_value=core):
        with client.websocket_connect("/api/ws?device_token=fluai_dev_ws_123") as ws:
            handshake = ws.receive_json()
            assert handshake["type"] == "state_change"

            ws.send_json({
                "type": "stream_chat",
                "prompt": "Namaste kaise ho?",
                "session_id": "ws_gw_test",
                "speak": False,
            })
            events = []
            while True:
                ev = ws.receive_json()
                events.append(ev)
                if ev.get("type") == "final_response" or len(events) >= 6:
                    break

            chunk_msgs = [e for e in events if e.get("type") == "stream_chunk"]
            final_msgs = [e for e in events if e.get("type") == "final_response"]
            assert chunk_msgs and chunk_msgs[0]["data"]["chunk"] == "Diffy gateway reply over WS."
            assert final_msgs and final_msgs[0]["data"]["response"] == "Diffy gateway reply over WS."
            mock_agent.chat_completion.assert_awaited_once()
            assert mock_agent.chat_completion.call_args.kwargs["device_token"] == "fluai_dev_ws_123"
