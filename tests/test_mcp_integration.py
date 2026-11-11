import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from google.genai import types

from backend.ai.gemini_service import GeminiService
from backend.ai.mcp_client import (
    MCPSkillsClient,
    _mcp_tools_to_gemini_tool,
    _sanitize_json_schema,
)
from backend.config.settings import Settings


class _FakeTool:
    def __init__(self, name: str, description: str, schema: dict):
        self.name = name
        self.description = description
        self.inputSchema = schema


class _FakeCallResult:
    def __init__(self, text: str):
        self.content = [SimpleNamespace(text=text)]
        self.data = text


class _FakeFastMCPClient:
    """In-memory stand-in for fastmcp.Client during unit tests."""

    def __init__(self, fail_connect: bool = False):
        self.fail_connect = fail_connect
        self.called = []

    async def __aenter__(self):
        if self.fail_connect:
            raise ConnectionRefusedError("Diffy MCP offline")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def list_tools(self):
        return [
            _FakeTool(
                "list_skills",
                "List available skills",
                {"type": "object", "properties": {}, "additionalProperties": False},
            ),
            _FakeTool(
                "get_skill",
                "Get skill instructions by name",
                {
                    "type": "object",
                    "properties": {"skill_name": {"type": "string", "title": "Skill Name"}},
                    "required": ["skill_name"],
                    "additionalProperties": False,
                },
            ),
        ]

    async def call_tool(self, name: str, arguments: dict | None = None):
        args = arguments or {}
        self.called.append((name, args))
        if name == "list_skills":
            return _FakeCallResult(
                json.dumps([
                    {
                        "name": "etar-framework",
                        "description": "Applies the ETAR Framework across Experiential, Thought, Action, Reality dimensions.",
                        "source": "local",
                    }
                ])
            )
        if name == "get_skill":
            if args.get("skill_name") == "etar-framework":
                return _FakeCallResult("ETAR stands for Experiential, Thought, Action, and Reality.")
            return _FakeCallResult(
                "SKILL_NOT_FOUND: 'unknown' does not exist in local or GitHub. "
                "STOP HERE. Do NOT answer from your general knowledge. "
                "Reply to the user with exactly this message: i have not record with your answer"
            )
        return _FakeCallResult("")


def test_sanitize_json_schema_removes_unsupported_keys_recursively():
    """Verify additionalProperties booleans and $schema are stripped cleanly for Gemini."""
    raw = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "nested": {
                "type": "object",
                "title": "Nested",
                "additionalProperties": False,
                "properties": {"x": {"type": "string"}},
            }
        },
    }
    clean = _sanitize_json_schema(raw)
    assert "$schema" not in clean
    assert "additionalProperties" not in clean
    assert "additionalProperties" not in clean["properties"]["nested"]
    assert "title" not in clean["properties"]["nested"]

    tool = _mcp_tools_to_gemini_tool([_FakeTool("demo", "Demo tool", raw)])
    assert tool is not None
    assert len(tool.function_declarations) == 1


def test_settings_safe_dict_does_not_leak_mcp_api_key():
    """Verify safe config exposure includes MCP mode/url without exposing MCP_API_KEY."""
    settings = Settings(mcp_api_key="super_secret_mcp_token", mcp_mode="hybrid")
    safe = settings.get_safe_dict()
    assert safe["mcp_enabled"] is True
    assert safe["mcp_mode"] == "hybrid"
    assert "mcp_api_key" not in safe
    assert "super_secret_mcp_token" not in json.dumps(safe)


@pytest.mark.asyncio
async def test_mcp_client_hybrid_vs_strict_skill_not_found():
    """Verify Hybrid Mode overrides strict SKILL_NOT_FOUND refusal whereas Strict Mode keeps it."""
    fake_mcp = _FakeFastMCPClient()

    hybrid_client = MCPSkillsClient(
        settings=Settings(mcp_enabled=True, mcp_mode="hybrid"),
        client_factory=lambda _t: fake_mcp,
    )
    tool, sys_prompt, meta = await hybrid_client.prepare_prompt_context("Be concise.")
    assert meta["mcp_active"] is True
    assert tool is not None
    assert "etar-framework" in sys_prompt
    assert "HYBRID RULES" in sys_prompt

    res_hybrid = await hybrid_client.call_tools_batch([("get_skill", {"skill_name": "missing"})])
    assert "Hybrid Mode is active" in res_hybrid[0]
    assert "i have not record with your answer" not in res_hybrid[0]

    strict_client = MCPSkillsClient(
        settings=Settings(mcp_enabled=True, mcp_mode="strict"),
        client_factory=lambda _t: fake_mcp,
    )
    res_strict = await strict_client.call_tools_batch([("get_skill", {"skill_name": "missing"})])
    assert "i have not record with your answer" in res_strict[0]


@pytest.mark.asyncio
async def test_mcp_client_graceful_fallback_when_offline():
    """Verify ProductSpeaker stays functional when Diffy MCP server is stopped."""
    offline_mcp = _FakeFastMCPClient(fail_connect=True)
    client = MCPSkillsClient(
        settings=Settings(mcp_enabled=True, mcp_mode="hybrid"),
        client_factory=lambda _t: offline_mcp,
    )
    tool, sys_prompt, meta = await client.prepare_prompt_context("Base prompt.")
    assert tool is None
    assert sys_prompt == "Base prompt."
    assert meta["mcp_active"] is False

    status = await client.get_status()
    assert status["connected"] is False


@pytest.mark.asyncio
async def test_gemini_service_multi_turn_mcp_tool_loop():
    """Verify GeminiService executes Diffy MCP tool calls and passes results back to Gemini."""
    fake_mcp = _FakeFastMCPClient()
    mcp_client = MCPSkillsClient(
        settings=Settings(mcp_enabled=True, mcp_mode="hybrid"),
        client_factory=lambda _t: fake_mcp,
    )
    service = GeminiService(
        settings=Settings(gemini_api_key="test_key", mcp_enabled=True, mcp_mode="hybrid"),
        mcp_client=mcp_client,
    )

    fc = SimpleNamespace(name="get_skill", args={"skill_name": "etar-framework"})
    turn1_content = types.Content(
        role="model",
        parts=[types.Part.from_function_call(name="get_skill", args={"skill_name": "etar-framework"})],
    )
    resp_turn1 = SimpleNamespace(
        function_calls=[fc],
        candidates=[SimpleNamespace(content=turn1_content)],
        text="",
    )
    resp_turn2 = SimpleNamespace(
        function_calls=[],
        candidates=[],
        text="ETAR stands for Experiential, Thought, Action, and Reality dimensions.",
    )

    mock_genai = MagicMock()
    mock_genai.models.generate_content.side_effect = [resp_turn1, resp_turn2]
    service._get_client = lambda: mock_genai

    answer, _latency = await service.generate_response("What is ETAR framework?")
    assert "Experiential, Thought, Action, and Reality" in answer
    assert ("get_skill", {"skill_name": "etar-framework"}) in fake_mcp.called
    assert mock_genai.models.generate_content.call_count == 2


def test_stt_silence_and_hallucination_guards():
    """Verify quiet/silent WAV RMS check and '00:00' non-speech filter prevent 30s-55s STT stalls."""
    import io
    import struct
    import wave
    from backend.voice.speech_to_text import _compute_wav_rms, _is_non_speech_transcript

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(struct.pack("<1600h", *([10] * 1600)))

    rms = _compute_wav_rms(buf.getvalue())
    assert rms is not None and rms < 200.0
    assert _is_non_speech_transcript("00:00") is True
    assert _is_non_speech_transcript("(silence)") is True
    assert _is_non_speech_transcript("list my MCP") is False


@pytest.mark.asyncio
async def test_mcp_client_stale_while_revalidate_nonblocking():
    """Verify expired MCP cache returns immediately once populated and refreshes in background."""
    import time
    fake_mcp = _FakeFastMCPClient()
    client = MCPSkillsClient(
        settings=Settings(mcp_enabled=True, mcp_mode="hybrid", mcp_cache_ttl_seconds=0.01),
        client_factory=lambda _t: fake_mcp,
    )
    assert await client.warm_up() is True
    client._last_success_ts = time.monotonic() - 10.0

    t0 = time.perf_counter()
    tool, _prompt, meta = await client.prepare_prompt_context("Base.")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert tool is not None
    assert meta["mcp_active"] is True
    assert elapsed_ms < 50.0
    if client._bg_refresh_task is not None:
        await client._bg_refresh_task

