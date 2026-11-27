"""Thin HTTP Client forwarding ProductSpeaker voice transcripts to Diffy Agent API."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

import httpx

from backend.config.settings import Settings, get_settings

logger = logging.getLogger("ai_voice_assistant.agent_gateway")


class AgentGatewayClient:
    """Forwards voice transcripts and device pairing calls to Diffy Agent API."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()

    @property
    def base_url(self) -> str:
        return (self.settings.diffy_agent_api_url or "http://127.0.0.1:3001").rstrip("/")

    async def verify_connection(self) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{self.base_url}/health")
                if r.status_code == 200:
                    data = r.json()
                    return {"status": "connected", "url": self.base_url, "details": data}
                return {"status": "error", "code": r.status_code}
        except Exception as e:
            return {"status": "unreachable", "error": str(e)}

    async def pair_device(
        self,
        device_id: str,
        user_id: str,
        device_name: str = "ESP32 Speaker",
    ) -> Dict[str, Any]:
        """Register an ESP32 device with a canonical Open WebUI user_id via Diffy Agent API."""
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.settings.mcp_api_key:
            headers["Authorization"] = f"Bearer {self.settings.mcp_api_key}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.base_url}/v1/devices/pair",
                headers=headers,
                json={"device_id": device_id, "user_id": user_id, "device_name": device_name},
            )
            resp.raise_for_status()
            return resp.json()

    async def resolve_device_token(self, device_token: str) -> Optional[Dict[str, Any]]:
        """Validate a per-device bearer token against Diffy Agent API."""
        if not device_token:
            return None
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.settings.mcp_api_key:
            headers["Authorization"] = f"Bearer {self.settings.mcp_api_key}"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/devices/resolve",
                    headers=headers,
                    json={"device_token": device_token},
                )
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            logger.warning(f"Device token verification failed: {e}")
        return None

    async def chat_completion(
        self,
        prompt: str,
        session_id: str,
        device_token: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> Tuple[str, float]:
        """Forward transcript to Diffy Agent API /v1/chat/completions and return (reply, latency_ms)."""
        t0 = time.perf_counter()
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "X-Channel": "speaker",
            "X-Session-Id": session_id,
        }
        token_to_use = (device_token or self.settings.device_token or "").strip()
        if token_to_use:
            headers["X-Device-Token"] = token_to_use
            headers["Authorization"] = f"Bearer {token_to_use}"
        elif self.settings.mcp_api_key:
            headers["Authorization"] = f"Bearer {self.settings.mcp_api_key}"

        payload = {
            "model": model_override or "diffy-agent",
            "messages": [{"role": "user", "content": prompt}],
            "session_id": session_id,
            "channel": "speaker",
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                reply = data["choices"][0]["message"]["content"].strip()
                latency_ms = (time.perf_counter() - t0) * 1000
                return reply, latency_ms
        except Exception as e:
            latency_ms = (time.perf_counter() - t0) * 1000
            logger.error(f"Diffy Agent API call failed ({latency_ms:.1f}ms): {e}")
            fallback = (
                "I am having a brief moment reconnecting to the assistant service. "
                "Please wait a few seconds and try speaking again."
            )
            return fallback, latency_ms


_agent_gateway_singleton: Optional[AgentGatewayClient] = None


def get_agent_gateway_client() -> AgentGatewayClient:
    global _agent_gateway_singleton
    if _agent_gateway_singleton is None:
        _agent_gateway_singleton = AgentGatewayClient()
    return _agent_gateway_singleton
