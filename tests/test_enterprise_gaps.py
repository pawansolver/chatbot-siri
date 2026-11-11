import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.ai.gemini_service import GeminiService
from backend.ai.mcp_client import MCPSkillsClient, MAX_TOOL_OUTPUT_CHARS, _compact_markdown_for_voice
from backend.api.routes import _sanitize_header_value
from backend.config.settings import Settings, get_settings
from backend.core.memory import SQLiteMemoryStore
from backend.core.session import SessionManager
from backend.core.state_manager import StateManager
from backend.main import create_app


class _FakeSkillMCPClient:
    call_count = 0

    def __init__(self, _timeout: float):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def list_tools(self):
        return [
            SimpleNamespace(
                name="get_skill",
                description="Fetch a skill by name",
                inputSchema={
                    "type": "object",
                    "properties": {"skill_name": {"type": "string"}},
                    "required": ["skill_name"],
                },
            )
        ]

    async def call_tool(self, name: str, args: dict):
        _FakeSkillMCPClient.call_count += 1
        if name == "get_skill":
            skill = args.get("skill_name", "demo")
            return SimpleNamespace(
                content=[SimpleNamespace(text=f"---\nname: {skill}\n---\nDetailed framework answer for {skill}.")]
            )
        return SimpleNamespace(content=[SimpleNamespace(text="[]")])


@pytest.mark.asyncio
async def test_mcp_get_skill_cache_and_voice_compaction():
    _FakeSkillMCPClient.call_count = 0
    settings = Settings(
        mcp_enabled=True,
        mcp_mode="hybrid",
        mcp_server_url="http://127.0.0.1:7860/mcp",
        mcp_cache_ttl_seconds=300.0,
    )
    client = MCPSkillsClient(settings=settings, client_factory=lambda t: _FakeSkillMCPClient(t))
    await client.warm_up()
    first = await client.call_tools_batch([("get_skill", {"skill_name": "etar"})], query_hint="ETAR summary")
    second = await client.call_tools_batch([("get_skill", {"skill_name": "etar"})], query_hint="ETAR summary")

    assert "Detailed framework answer for etar." in first[0]
    assert first == second
    # 1st call hit MCP server, 2nd call hit local cache
    assert _FakeSkillMCPClient.call_count == 1
    status = await client.get_status()
    assert status["cache_hits"] == 1
    assert status["cached_skill_entries"] == 1

    # Large markdown document is condensed cleanly preserving relevant sections
    big_doc = ("Intro overview.\n" * 400) + "\n## Target ETAR Architecture\nETAR uses edge routing.\n" + ("Filler\n" * 3000)
    compact = _compact_markdown_for_voice(big_doc, query_hint="ETAR Architecture")
    assert len(compact) <= MAX_TOOL_OUTPUT_CHARS + 50
    assert "ETAR uses edge routing." in compact


@pytest.mark.asyncio
async def test_gemini_circuit_breaker_and_qa_cache():
    settings = Settings(
        gemini_api_key="test-key",
        gemini_model="model-primary",
        mcp_enabled=False,
    )
    mcp_disabled = MCPSkillsClient(settings=settings)
    svc = GeminiService(settings=settings, mcp_client=mcp_disabled)
    svc.CIRCUIT_FAILURE_THRESHOLD = 2

    calls = []

    def _fake_generate(model, contents, config):
        calls.append(model)
        if model == "model-primary":
            raise RuntimeError("503 UNAVAILABLE")
        return SimpleNamespace(text="Healthy fallback answer.", function_calls=[], candidates=[])

    svc._client = SimpleNamespace(models=SimpleNamespace(generate_content=_fake_generate))
    svc._last_key = "test-key"

    # Two failures trip circuit breaker on model-primary while succeeding via fallback
    r1, _ = await svc.generate_response("Explain quantum computing")
    r2, _ = await svc.generate_response("Explain machine learning")
    assert r1 == "Healthy fallback answer."
    assert r2 == "Healthy fallback answer."
    diag = svc.get_diagnostics()
    assert diag["circuits"]["model-primary"]["state"] == "open"

    # Next non-cached question skips open circuit model-primary immediately
    calls.clear()
    r3, _ = await svc.generate_response("Explain cloud computing")
    assert r3 == "Healthy fallback answer."
    assert "model-primary" not in calls

    # Repeated identical non-volatile question serves from Q&A cache without invoking SDK
    calls.clear()
    r4, _ = await svc.generate_response("Explain cloud computing")
    assert r4 == "Healthy fallback answer."
    assert calls == []
    assert svc.get_diagnostics()["response_cache_hits"] == 1

    # Volatile query ("time") never hits Q&A cache
    await svc.generate_response("What time is it?")
    await svc.generate_response("What time is it?")
    assert len(calls) >= 2


@pytest.mark.asyncio
async def test_state_manager_per_device_locks_do_not_block_each_other():
    mgr = StateManager()
    events = []

    async def _worker(session_id: str, delay: float):
        async with mgr.acquire_lock(session_id):
            events.append((session_id, "enter"))
            await asyncio.sleep(delay)
            events.append((session_id, "exit"))

    t0 = time.perf_counter()
    await asyncio.gather(_worker("esp32_dev1", 0.12), _worker("esp32_dev2", 0.12))
    elapsed = time.perf_counter() - t0

    # Parallel per-device locks run concurrently (~0.12s), well below serialized 0.24s
    assert elapsed < 0.21
    # Both devices entered before either exited
    assert events[0][1] == "enter" and events[1][1] == "enter"

    # Default lock without args still works for backward compatibility
    async with mgr.acquire_lock():
        assert mgr.acquire_lock() is mgr.acquire_lock(None)


@pytest.mark.asyncio
async def test_sqlite_session_and_fact_persistence_across_restart(tmp_path: Path):
    db_file = tmp_path / "sessions.db"

    mgr1 = SessionManager(db_path=str(db_file), enable_persistence=True)
    sess1 = mgr1.get_or_create_session("esp32_aabbccddeeff")
    sess1.conversation.add_user_message("Mera naam Pawan hai", source="voice")
    sess1.conversation.add_assistant_message("Namaste Pawan! Kaise madad kar sakta hoon?")
    mgr1._store.close()

    # Recreate SessionManager simulating backend restart
    mgr2 = SessionManager(db_path=str(db_file), enable_persistence=True)
    sess2 = mgr2.get_or_create_session("esp32_aabbccddeeff")
    ctx = sess2.conversation.get_gemini_context()
    assert len(ctx) == 2
    assert ctx[0]["text"] == "Mera naam Pawan hai"
    assert "Namaste Pawan" in ctx[1]["text"]

    # Long-term fact persistence
    store = SQLiteMemoryStore(str(db_file))
    await store.store_fact("preferred_city", "Mumbai", user_id="esp32_aabbccddeeff")
    facts = await store.retrieve_context("city", user_id="esp32_aabbccddeeff")
    assert any("Mumbai" in f for f in facts)

    # Clear removes persisted messages too
    sess2.conversation.clear()
    mgr2._store.close()
    store.close()

    mgr3 = SessionManager(db_path=str(db_file), enable_persistence=True)
    sess3 = mgr3.get_or_create_session("esp32_aabbccddeeff")
    assert sess3.conversation.get_history() == []
    mgr3._store.close()


def test_device_api_key_auth_and_header_sanitization(monkeypatch):
    monkeypatch.setenv("DEVICE_API_KEY", "enterprise-secret-99")
    get_settings.cache_clear()
    try:
        app = create_app()
        client = TestClient(app)

        # Health endpoints remain open for orchestrator probes
        assert client.get("/health/live").status_code == 200

        # Protected /api routes reject missing or wrong key
        assert client.get("/api/config").status_code == 401
        assert client.get("/api/config", headers={"X-API-Key": "wrong"}).status_code == 401

        # Correct key succeeds
        ok = client.get("/api/config", headers={"X-API-Key": "enterprise-secret-99"})
        assert ok.status_code == 200
        assert ok.json()["auth_required"] is True
    finally:
        monkeypatch.delenv("DEVICE_API_KEY", raising=False)
        get_settings.cache_clear()

    assert _sanitize_header_value("Hello\r\nWorld\n\tनमस्ते") == "Hello World"


def test_deployment_files_hygiene():
    root = Path(__file__).resolve().parent.parent
    reqs = (root / "requirements.txt").read_text(encoding="utf-8")
    assert "miniaudio>=" in reqs
    assert "fastmcp>=" in reqs

    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    assert "EXPOSE 8000" in dockerfile
    assert "/health/live" in dockerfile
    assert (root / ".dockerignore").exists()
