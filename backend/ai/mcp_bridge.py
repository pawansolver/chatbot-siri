"""FastMCP Client Bridge for Smart Human Problem Understanding & Skill Routing.

Provides a unified, resilient client for Diffy FastMCP with:
- Native Streamable HTTP protocol handling
- Connection reuse and session pooling (avoids handshake per call)
- Transparent session expiration detection and automatic reconnection
- Concurrency-safe request execution
- High-level methods for all 5 core Diffy tools
- Parameter normalization (e.g. text <-> user_input, problem_analysis <-> analysis)
- Emergency local safety screening fallback (NEVER bypasses safety on MCP failure)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx

try:
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport
except ImportError:
    Client = None
    StreamableHttpTransport = None

logger = logging.getLogger("fastmcp.bridge")

# Emergency local keyword patterns for safety screening when Diffy is unreachable
CRITICAL_SAFETY_PATTERNS = {
    "self_harm": [
        r"\b(suicide|kill\s+myself|end\s+my\s+life|want\s+to\s+die|cut\s+myself|hanging\s+myself|take\s+all\s+the\s+pills)\b",
        r"(आत्महत्या|जान\s*देना|मर\s*जाना|जिंदगी\s*खत्म|खुद\s*को\s*मार)",
        r"\b(apni\s+jaan|marna\s+chahta|suicide\s+kar\s+lunga)\b",
    ],
    "domestic_violence": [
        r"\b(hit\s+me|beat\s+me|slapped\s+me|threatened\s+to\s+kill|choked\s+me|locked\s+me\s+in|broke\s+my\s+bones)\b",
        r"(मारा|पीटा|थप्पड़|गला\s*दबाया|बंद\s*कर\s*दिया|जान\s*से\s*मारने\s*की\s*धमकी)",
        r"\b(mara|peeta|thappad|jaan\s+se\s+marne\s+ki\s+dhamki|choke\s+kiya)\b",
    ],
    "child_abuse": [
        r"\b(abusing\s+the\s+child|starving\s+the\s+baby|locks?\s+the\s+child|hitting\s+the\s+toddler)\b",
        r"(बच्चे\s*को\s*मारना|भूखा\s*रखना|बाल\s*उत्पीड़न)",
    ],
    "threat_immediate_harm": [
        r"\b(bomb|gun|weapon|murder|smash\s+his\s+head|break\s+his\s+legs)\b",
        r"(हथियार|गोली|मार\s*दूंगा|खून\s*कर\s*दूंगा)",
    ],
}


def _local_safety_fallback_screen(user_input: str) -> Dict[str, Any]:
    """Fallback safety scanner if Diffy MCP is down.

    Ensures we NEVER silently bypass safety when Diffy is unavailable.
    """
    clean_text = user_input.lower()
    detected_indicators = []

    for indicator, patterns in CRITICAL_SAFETY_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, clean_text, re.IGNORECASE):
                detected_indicators.append(indicator)
                break

    if detected_indicators:
        return {
            "understanding": {
                "summary": "CRITICAL safety distress detected via local emergency rule-engine fallback.",
                "domains": ["individual_emotional_support"],
                "people_involved": ["self_individual"],
                "problem_patterns": ["acute_crisis", "physical_or_psychological_harm"],
                "emotional_signals": ["terror", "despair"],
                "user_intention": ["safety_seeking"],
                "contextual_factors": ["mcp_offline_emergency_fallback"],
            },
            "safety": {
                "potential_risk": True,
                "risk_categories": detected_indicators,
                "requires_safe_followup": True,
                "reason": f"Detected critical risk indicators: {detected_indicators}",
            },
            "confidence": {"overall": 0.95, "classification": 0.95},
            "uncertainty": ["evaluated_via_emergency_fallback_screener"],
            "needs_clarification": False,
            "clarification_question": None,
            "safety_lockout": True,
            "requires_emergency_protocol": True,
        }

    return {
        "understanding": {
            "summary": "Non-emergency input evaluated via local fallback screener (Diffy MCP unavailable).",
            "domains": ["unknown_or_other"],
            "people_involved": [],
            "problem_patterns": [],
            "emotional_signals": [],
            "user_intention": ["general_inquiry"],
            "contextual_factors": ["mcp_offline_fallback"],
        },
        "safety": {
            "potential_risk": False,
            "risk_categories": [],
            "requires_safe_followup": False,
            "reason": None,
        },
        "confidence": {"overall": 0.3, "classification": 0.3},
        "uncertainty": ["diffy_mcp_offline"],
        "needs_clarification": False,
        "clarification_question": None,
        "safety_lockout": False,
        "requires_emergency_protocol": False,
    }


class FastMCPBridge:
    """Enterprise client bridge for Diffy FastMCP server.

    Manages persistent Streamable HTTP connections, automatic reconnections,
    concurrency serialization, and fallback safety screening.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:7860/mcp",
        api_key: Optional[str] = None,
        timeout: float = 15.0,
        httpx_client_factory: Optional[Any] = None,
    ):
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/mcp"):
            self.base_url = f"{self.base_url}/mcp"
        self.api_key = api_key
        self.timeout = timeout
        self.httpx_client_factory = httpx_client_factory

        self._client: Optional[Client] = None
        self._lock = asyncio.Lock()
        self._is_connected = False
        self._last_error: Optional[str] = None
        self._tools_cache: Optional[List[Dict[str, Any]]] = None
        self._skills_cache: Optional[List[Dict[str, Any]]] = None
        self._last_skills_fetch = 0.0
        self._in_flight_count: int = 0

    @property
    def is_connected(self) -> bool:
        if not self._is_connected or self._client is None:
            return False
        try:
            return bool(self._client.is_connected())
        except Exception:
            return False

    def _build_transport(self) -> StreamableHttpTransport:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        return StreamableHttpTransport(
            url=self.base_url,
            headers=headers if headers else None,
            httpx_client_factory=self.httpx_client_factory,
        )

    async def connect(self) -> bool:
        """Establish or refresh the active FastMCP connection."""
        async with self._lock:
            if self.is_connected and self._client is not None:
                return True

            try:
                transport = self._build_transport()
                client = Client(
                    transport=transport,
                    timeout=self.timeout,
                    auto_initialize=True,
                )
                await client.__aenter__()
                self._client = client
                self._is_connected = True
                self._last_error = None
                logger.info(f"FastMCPBridge connected successfully to {self.base_url}")
                return True
            except Exception as e:
                self._is_connected = False
                self._client = None
                self._last_error = str(e)
                logger.warning(f"FastMCPBridge failed to connect to {self.base_url}: {e}")
                return False

    async def disconnect(self) -> None:
        """Gracefully disconnect and release connection resources."""
        async with self._lock:
            client = self._client
            self._client = None
            self._is_connected = False
            if client is not None:
                try:
                    await client.__aexit__(None, None, None)
                except Exception as e:
                    logger.debug(f"Error during disconnect: {e}")

    async def __aenter__(self) -> FastMCPBridge:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()

    async def call_tool(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        retries: int = 1,
    ) -> Any:
        """Call an MCP tool with session management and automatic reconnection."""
        args = arguments or {}

        # Normalize arguments for known Diffy tools
        if name == "understand_human_problem":
            if "text" in args and "user_input" not in args:
                args = {"user_input": args["text"], "conversation_history": args.get("conversation_history")}
            elif "user_input" not in args:
                args = {"user_input": str(args), "conversation_history": []}
        elif name == "route_skills":
            if "problem_analysis" in args and "analysis" not in args:
                args = {"analysis": args["problem_analysis"], "query_hint": args.get("query_hint")}

        for attempt in range(retries + 1):
            if not self.is_connected:
                ok = await self.connect()
                if not ok:
                    if attempt < retries:
                        await asyncio.sleep(0.5)
                        continue
                    raise ConnectionError(f"Cannot connect to Diffy FastMCP at {self.base_url}: {self._last_error}")

            client = self._client
            if client is None:
                continue

            self._in_flight_count += 1
            try:
                res = await client.call_tool(name, args)
                if hasattr(res, "data") and res.data is not None:
                    return res.data
                if hasattr(res, "content") and isinstance(res.content, list) and res.content:
                    text_out = getattr(res.content[0], "text", str(res.content[0]))
                    try:
                        return json.loads(text_out)
                    except Exception:
                        return text_out
                return res
            except Exception as e:
                logger.warning(f"FastMCP call_tool '{name}' attempt {attempt+1} failed: {e}")
                is_conn_error = (
                    isinstance(e, (ConnectionError, EOFError, BrokenPipeError))
                    or "closed" in str(e).lower()
                    or "connection" in str(e).lower()
                    or "timeout" in str(e).lower()
                    or "stream" in str(e).lower()
                )
                if is_conn_error:
                    async with self._lock:
                        if self._client is client:
                            self._client = None
                            self._is_connected = False
                            try:
                                await client.__aexit__(None, None, None)
                            except Exception:
                                pass
                if attempt < retries and is_conn_error:
                    await asyncio.sleep(0.5)
                else:
                    raise
            finally:
                self._in_flight_count = max(0, self._in_flight_count - 1)

    async def list_tools(self) -> List[Dict[str, Any]]:
        """List all tools registered on the FastMCP server."""
        if not self.is_connected:
            await self.connect()

        if not self.is_connected:
            raise ConnectionError(f"Cannot connect to FastMCP: {self._last_error}")

        client = self._client
        if client is None:
            raise ConnectionError("FastMCP client is not connected")

        tools = await client.list_tools()
        self._tools_cache = [
            {
                "name": t.name,
                "description": getattr(t, "description", ""),
                "inputSchema": getattr(t, "inputSchema", getattr(t, "input_schema", {})),
            }
            for t in tools
        ]
        return self._tools_cache

    # -------------------------------------------------------------------------
    # High-Level Helper Methods for Diffy Tools
    # -------------------------------------------------------------------------

    async def understand_human_problem(
        self,
        user_input: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Analyze user input with automatic fallback safety screening."""
        try:
            res = await self.call_tool(
                "understand_human_problem",
                {"user_input": user_input, "conversation_history": conversation_history or []},
                retries=1,
            )
            if isinstance(res, dict):
                return res
            if isinstance(res, str):
                try:
                    return json.loads(res)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Diffy MCP understand_human_problem failed ({e}). Engaging safety fallback screener.")

        # Emergency Fallback: Never bypass safety when Diffy is down!
        return _local_safety_fallback_screen(user_input)

    async def route_skills(
        self,
        analysis: Dict[str, Any],
        query_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Route skills based on problem analysis."""
        try:
            res = await self.call_tool(
                "route_skills",
                {"analysis": analysis, "query_hint": query_hint},
                retries=1,
            )
            if isinstance(res, dict):
                return res
            if isinstance(res, str):
                try:
                    return json.loads(res)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Diffy MCP route_skills failed ({e}). Using safety safeguard routing.")

        # Fallback routing
        is_risk = analysis.get("safety", {}).get("potential_risk", False) or analysis.get("safety_lockout", False)
        if is_risk:
            return {
                "selected_skills": [
                    {"skill_id": "suicide-crisis-safeguard" if "self_harm" in str(analysis) else "domestic-violence-safeguard",
                     "tier": "safety_boundary",
                     "selection_reason": "Emergency safety fallback activation"}
                ],
                "safety_guidance": ["Prioritize immediate physical safety and certified crisis helplines."],
                "safety_lockout": True,
                "requires_emergency_protocol": True,
            }

        return {
            "selected_skills": [
                {"skill_id": "active-listening", "tier": "core_conversation", "selection_reason": "Fallback core support"},
                {"skill_id": "empathy-validation", "tier": "core_conversation", "selection_reason": "Fallback core support"},
            ],
            "safety_guidance": [],
            "safety_lockout": False,
            "requires_emergency_protocol": False,
        }

    async def list_skills(self, ttl: float = 300.0) -> List[Dict[str, str]]:
        """Fetch full skills catalog with caching."""
        now = time.monotonic()
        if self._skills_cache and (now - self._last_skills_fetch) < ttl:
            return self._skills_cache

        try:
            res = await self.call_tool("list_skills", {}, retries=1)
            if isinstance(res, list):
                self._skills_cache = res
                self._last_skills_fetch = now
                return res
            if isinstance(res, str):
                parsed = json.loads(res)
                if isinstance(parsed, list):
                    self._skills_cache = parsed
                    self._last_skills_fetch = now
                    return parsed
        except Exception as e:
            logger.warning(f"list_skills failed: {e}")
            if self._skills_cache:
                return self._skills_cache

        return []

    async def get_skill(self, skill_name: str) -> str:
        """Fetch full SKILL.md content for a given skill."""
        res = await self.call_tool("get_skill", {"skill_name": skill_name}, retries=1)
        return str(res)

    async def list_skill_files(self, skill_name: str) -> List[str]:
        """Fetch file list for a specific skill."""
        res = await self.call_tool("list_skill_files", {"skill_name": skill_name}, retries=1)
        if isinstance(res, list):
            return res
        if isinstance(res, str):
            try:
                parsed = json.loads(res)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
        return []
