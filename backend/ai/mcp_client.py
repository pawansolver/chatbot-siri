import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from google.genai import types

from backend.ai.mcp_bridge import FastMCPBridge, _local_safety_fallback_screen
from backend.config.settings import Settings, get_settings

logger = logging.getLogger("ai_voice_assistant.mcp")

MAX_TOOL_OUTPUT_CHARS = 12000
MAX_SKILL_RAW_CACHE_CHARS = 45000
MAX_SKILL_DESC_IN_PROMPT = 140
SKILL_PREVIEW_CHARS = 3500
UNSUPPORTED_SCHEMA_KEYS = frozenset({"additionalProperties", "$schema", "title"})
CACHEABLE_READ_TOOLS = frozenset({"list_skills", "get_skill", "list_skill_files"})


def _compact_markdown_for_voice(text: str, query_hint: Optional[str] = None, max_chars: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    """Keep concise spoken-relevant sections when a Diffy skill doc exceeds max_chars."""
    if len(text) <= max_chars:
        return text

    # Preserve frontmatter + intro always
    intro = text[:SKILL_PREVIEW_CHARS]
    remaining_budget = max_chars - len(intro) - 80

    if not query_hint or remaining_budget <= 400:
        return text[:max_chars] + "\n...[truncated for voice latency]"

    keywords = {
        word.lower()
        for word in query_hint.replace("?", " ").replace(",", " ").split()
        if len(word) >= 3
    }
    sections = text[SKILL_PREVIEW_CHARS:].split("\n## ")
    scored: List[Tuple[int, int, str]] = []
    for idx, sec in enumerate(sections):
        sec_text = ("\n## " + sec) if idx > 0 else sec
        sec_lower = sec_text.lower()
        hits = sum(1 for kw in keywords if kw in sec_lower)
        scored.append((hits, -idx, sec_text))

    # Highest keyword matches first, preserving document order on ties
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected: List[str] = []
    used = 0
    for _hits, _neg_idx, sec_text in scored:
        if used >= remaining_budget:
            break
        chunk = sec_text[: remaining_budget - used]
        selected.append(chunk)
        used += len(chunk)

    combined = intro + ("\n" + "\n".join(selected) if selected else "")
    if len(combined) > max_chars:
        combined = combined[:max_chars]
    return combined + "\n...[condensed for voice latency]"


def _sanitize_json_schema(node: Any) -> Any:
    """Recursively strip JSON Schema keys (e.g. additionalProperties: false) incompatible with Gemini."""
    if isinstance(node, dict):
        return {
            k: _sanitize_json_schema(v)
            for k, v in node.items()
            if k not in UNSUPPORTED_SCHEMA_KEYS
        }
    if isinstance(node, list):
        return [_sanitize_json_schema(item) for item in node]
    return node


def _mcp_tools_to_gemini_tool(mcp_tools: List[Any]) -> Optional[types.Tool]:
    """Convert MCP tool definitions into a single Google GenAI Tool wrapper."""
    declarations: List[types.FunctionDeclaration] = []
    for tool in mcp_tools:
        name = getattr(tool, "name", None)
        if not name:
            continue
        raw_schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {"type": "object", "properties": {}}
        clean_schema = _sanitize_json_schema(raw_schema)
        declarations.append(
            types.FunctionDeclaration(
                name=name,
                description=getattr(tool, "description", "") or "",
                parameters_json_schema=clean_schema,
            )
        )
    if not declarations:
        return None
    return types.Tool(function_declarations=declarations)


def _extract_tool_text(result: Any) -> str:
    """Extract clean text content from a FastMCP CallToolResult."""
    if result is None:
        return ""
    content = getattr(result, "content", None)
    if isinstance(content, list) and content:
        parts: List[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text is not None:
                parts.append(str(text))
            else:
                parts.append(str(item))
        combined = "\n".join(parts).strip()
    elif getattr(result, "data", None) is not None:
        data = result.data
        combined = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    else:
        combined = str(result)

    if len(combined) > MAX_SKILL_RAW_CACHE_CHARS:
        return combined[:MAX_SKILL_RAW_CACHE_CHARS] + "\n...[truncated]"
    return combined


def _parse_skills_catalog(raw_text: str) -> List[Dict[str, str]]:
    """Parse JSON skill summaries returned by diffy-main list_skills."""
    if not raw_text:
        return []
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, list):
            skills: List[Dict[str, str]] = []
            for entry in parsed:
                if isinstance(entry, dict) and entry.get("name"):
                    desc = " ".join(str(entry.get("description", "")).split())
                    if len(desc) > MAX_SKILL_DESC_IN_PROMPT:
                        desc = desc[: MAX_SKILL_DESC_IN_PROMPT - 3] + "..."
                    skills.append({
                        "name": str(entry["name"]),
                        "description": desc,
                        "source": str(entry.get("source", "local")),
                    })
            return skills
    except Exception:
        pass
    return []


class MCPSkillsClient:
    """Async MCP client bridging ProductSpeaker voice AI with diffy-main Skills Provider."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client_factory: Optional[Callable[[float], Any]] = None,
    ):
        self.settings = settings or get_settings()
        self._client_factory = client_factory
        self._lock = asyncio.Lock()

        self._cached_gemini_tool: Optional[types.Tool] = None
        self._cached_tool_names: List[str] = []
        self._cached_skills: List[Dict[str, str]] = []
        self._cached_raw_skills_text: str = ""
        self._last_success_ts: float = 0.0
        self._last_failure_ts: float = 0.0
        self._last_error: Optional[str] = None
        self._failure_cooldown_seconds: float = 5.0
        self._bg_refresh_task: Optional[asyncio.Task] = None

        # TTL cache for get_skill / list_skill_files / read-only MCP payloads
        self._tool_result_cache: Dict[Tuple[str, str], Tuple[float, str]] = {}
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        self._bridge: Optional[FastMCPBridge] = None

    def get_bridge(self) -> FastMCPBridge:
        """Get or initialize persistent shared FastMCPBridge."""
        if self._bridge is None:
            self._bridge = FastMCPBridge(
                base_url=self.settings.mcp_server_url,
                api_key=self.settings.mcp_api_key,
                timeout=float(self.settings.mcp_timeout_seconds),
            )
        return self._bridge

    async def understand_human_problem(
        self,
        user_input: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Pre-generation problem understanding through FastMCP or emergency safety fallback."""
        if not self.is_active:
            return _local_safety_fallback_screen(user_input)
        bridge = self.get_bridge()
        return await bridge.understand_human_problem(user_input, conversation_history)

    async def route_skills(
        self,
        analysis: Dict[str, Any],
        query_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Route skills dynamically based on problem analysis."""
        bridge = self.get_bridge()
        return await bridge.route_skills(analysis, query_hint)

    @property
    def is_active(self) -> bool:
        """Whether Diffy MCP integration is enabled in configuration."""
        return (
            bool(self.settings.mcp_enabled)
            and self.settings.mcp_mode != "off"
            and bool(self.settings.mcp_server_url.strip())
        )

    def _build_client(self, timeout_seconds: Optional[float] = None) -> Any:
        """Create a FastMCP HTTP Client configured with optional Bearer auth."""
        timeout = timeout_seconds if timeout_seconds is not None else self.settings.mcp_timeout_seconds
        if self._client_factory is not None:
            return self._client_factory(timeout)

        headers: Dict[str, str] = {}
        api_key = (self.settings.mcp_api_key or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        transport = StreamableHttpTransport(
            url=self.settings.mcp_server_url.strip(),
            headers=headers or None,
        )
        return Client(transport, timeout=timeout)

    def _normalize_tool_output(self, tool_name: str, text: str) -> str:
        """Adapt strict Diffy SKILL_NOT_FOUND directive when Hybrid Mode is active."""
        if (
            self.settings.mcp_mode == "hybrid"
            and tool_name == "get_skill"
            and text.lstrip().startswith("SKILL_NOT_FOUND:")
        ):
            return (
                "SKILL_NOT_FOUND: No matching skill exists in Diffy MCP for this name. "
                "Hybrid Mode is active: answer the user concisely using your general knowledge instead."
            )
        return text

    def _schedule_background_refresh(self) -> None:
        """Refresh expired MCP cache asynchronously without blocking active voice turns."""
        if self._bg_refresh_task is not None and not self._bg_refresh_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
            self._bg_refresh_task = loop.create_task(self._refresh_cache_if_needed(force=True))
        except RuntimeError:
            pass

    async def _refresh_cache_if_needed(self, force: bool = False) -> bool:
        """Fetch MCP tools and skill catalog from diffy-main if cache is stale."""
        if not self.is_active:
            return False

        now = time.monotonic()
        cache_valid = (
            self._cached_gemini_tool is not None
            and (now - self._last_success_ts) < self.settings.mcp_cache_ttl_seconds
        )
        if not force and cache_valid:
            return True

        # Stale-while-revalidate: never stall an active user voice request once cache exists
        if not force and self._cached_gemini_tool is not None:
            self._schedule_background_refresh()
            return True

        if not force and self._last_failure_ts > 0 and (now - self._last_failure_ts) < self._failure_cooldown_seconds:
            return False

        async with self._lock:
            now = time.monotonic()
            cache_valid = (
                self._cached_gemini_tool is not None
                and (now - self._last_success_ts) < self.settings.mcp_cache_ttl_seconds
            )
            if not force and cache_valid:
                return True
            if not force and self._last_failure_ts > 0 and (now - self._last_failure_ts) < self._failure_cooldown_seconds:
                return False

            connect_timeout = float(self.settings.mcp_timeout_seconds)
            try:
                async with self._build_client(connect_timeout) as client:
                    mcp_tools = await client.list_tools()
                    gemini_tool = _mcp_tools_to_gemini_tool(mcp_tools)
                    tool_names = [getattr(t, "name", "") for t in mcp_tools if getattr(t, "name", "")]

                    skills: List[Dict[str, str]] = self._cached_skills
                    raw_skills_text = self._cached_raw_skills_text
                    if "list_skills" in tool_names:
                        raw_skills_res = await client.call_tool("list_skills", {})
                        extracted_skills_text = _extract_tool_text(raw_skills_res)
                        parsed = _parse_skills_catalog(extracted_skills_text)
                        if parsed:
                            skills = parsed
                            raw_skills_text = extracted_skills_text

                self._cached_gemini_tool = gemini_tool
                self._cached_tool_names = tool_names
                self._cached_skills = skills
                self._cached_raw_skills_text = raw_skills_text
                self._last_success_ts = time.monotonic()
                self._last_failure_ts = 0.0
                self._last_error = None
                logger.info(
                    f"Diffy MCP synced ({self.settings.mcp_server_url}): "
                    f"tools={tool_names}, skills={len(skills)}"
                )
                return gemini_tool is not None
            except Exception as e:
                self._cached_gemini_tool = None
                self._last_failure_ts = time.monotonic()
                self._last_error = str(e)
                logger.warning(f"Diffy MCP unavailable at {self.settings.mcp_server_url}: {e}")
                return False

    async def warm_up(self) -> bool:
        """Warm the MCP tool and skill cache during application startup."""
        return await self._refresh_cache_if_needed(force=True)

    async def prepare_prompt_context(
        self,
        base_system_instruction: str,
    ) -> Tuple[Optional[types.Tool], str, Dict[str, Any]]:
        """Return (gemini_tool, effective_system_instruction, metadata) for a Gemini request."""
        if not self.is_active:
            return None, base_system_instruction, {"mcp_active": False, "mode": self.settings.mcp_mode}

        ready = await self._refresh_cache_if_needed(force=False)
        if not ready or self._cached_gemini_tool is None:
            return None, base_system_instruction, {
                "mcp_active": False,
                "mode": self.settings.mcp_mode,
                "error": self._last_error,
            }

        effective_instruction = self._build_system_instruction(base_system_instruction)
        return self._cached_gemini_tool, effective_instruction, {
            "mcp_active": True,
            "mode": self.settings.mcp_mode,
            "tools": list(self._cached_tool_names),
            "skills_count": len(self._cached_skills),
        }

    def _build_system_instruction(self, base_instruction: str) -> str:
        """Append Diffy MCP Hybrid/Strict instructions and skill index while preserving voice rules."""
        catalog_lines = [
            f"- {s['name']}: {s['description']}"
            for s in self._cached_skills
        ]
        catalog_block = "\n".join(catalog_lines) if catalog_lines else "(Call list_skills to inspect available skills.)"

        if self.settings.mcp_mode == "strict":
            mcp_block = (
                "\n\nDIFFY MCP STRICT SKILLS POLICY:\n"
                "You MUST check the Diffy MCP tools (list_skills / get_skill / list_skill_files) before answering. "
                "If a matching skill exists, call get_skill(skill_name) and answer using that skill. "
                "If no matching skill exists or get_skill returns SKILL_NOT_FOUND, reply ONLY with: i have not record with your answer\n"
                f"Available Diffy MCP Skills:\n{catalog_block}\n"
                "SPOKEN OUTPUT RULE: Reply in plain spoken text (1 to 3 concise sentences), matching the user's language, with no markdown."
            )
        else:
            mcp_block = (
                "\n\nDIFFY MCP HYBRID SKILLS POLICY:\n"
                "You have live access to the Diffy MCP Skills backend via tools (list_skills, get_skill, list_skill_files).\n"
                f"Currently indexed Diffy Skills:\n{catalog_block}\n"
                "HYBRID RULES:\n"
                "1. If the user's question relates to any indexed Diffy skill/framework above, or asks about Diffy/MCP/skills, "
                "you MUST call get_skill(skill_name) (or list_skills() to verify the latest skills) and base your answer on that skill.\n"
                "2. For general everyday questions outside Diffy skills (casual chat, weather, facts, GK, coding help, greetings), "
                "answer directly and fast using your general knowledge — NEVER refuse or say 'i have not record with your answer'.\n"
                "3. Keep ALL final spoken answers concise (1 to 3 short sentences) in the user's language (English, Hindi, or Hinglish), "
                "using plain spoken text with NO markdown, asterisks, or bullet lists."
            )
        return f"{base_instruction.rstrip()}{mcp_block}"

    def invalidate_cache(self) -> None:
        """Clear cached skill catalog and tool payloads."""
        self._tool_result_cache.clear()
        self._last_success_ts = 0.0

    def _is_cacheable_result(self, tool_name: str, raw_text: str) -> bool:
        """Return True if a successful read-only tool payload may be cached."""
        if tool_name not in CACHEABLE_READ_TOOLS or not raw_text:
            return False
        stripped = raw_text.lstrip()
        if stripped.startswith(("SKILL_NOT_FOUND:", "TOOL_ERROR", "MCP_UNAVAILABLE")):
            return False
        return True

    async def call_tools_batch(
        self,
        tool_calls: List[Tuple[str, Dict[str, Any]]],
        query_hint: Optional[str] = None,
    ) -> List[str]:
        """Execute one or more MCP tool calls, serving fresh cached skill reads locally."""
        if not tool_calls:
            return []

        now = time.monotonic()
        ttl = max(0.0, float(self.settings.mcp_cache_ttl_seconds))
        results: List[Optional[str]] = [None] * len(tool_calls)
        uncached_indices: List[int] = []

        for idx, (name, args) in enumerate(tool_calls):
            normalized_args = args or {}
            if (
                name == "list_skills"
                and not normalized_args
                and self._cached_raw_skills_text
                and (now - self._last_success_ts) < ttl
            ):
                self._cache_hits += 1
                results[idx] = self._cached_raw_skills_text
                continue

            cache_key = (name, json.dumps(normalized_args, sort_keys=True, ensure_ascii=False))
            if name in CACHEABLE_READ_TOOLS and ttl > 0:
                cached = self._tool_result_cache.get(cache_key)
                if cached and (now - cached[0]) < ttl:
                    self._cache_hits += 1
                    results[idx] = _compact_markdown_for_voice(
                        self._normalize_tool_output(name, cached[1]),
                        query_hint=query_hint,
                    )
                    continue

            self._cache_misses += 1
            uncached_indices.append(idx)

        if not uncached_indices:
            return [r or "" for r in results]

        try:
            if self._client_factory is not None:
                async with self._build_client(self.settings.mcp_timeout_seconds) as client:
                    for idx in uncached_indices:
                        name, args = tool_calls[idx]
                        normalized_args = args or {}
                        try:
                            res = await client.call_tool(name, normalized_args)
                            raw_text = _extract_tool_text(res)
                            if name == "list_skills":
                                parsed = _parse_skills_catalog(raw_text)
                                if parsed:
                                    self._cached_skills = parsed
                                    self._cached_raw_skills_text = raw_text
                                    self._last_success_ts = time.monotonic()
                            if self._is_cacheable_result(name, raw_text):
                                cache_key = (
                                    name,
                                    json.dumps(normalized_args, sort_keys=True, ensure_ascii=False),
                                )
                                self._tool_result_cache[cache_key] = (time.monotonic(), raw_text)
                            normalized = self._normalize_tool_output(name, raw_text)
                            results[idx] = _compact_markdown_for_voice(normalized, query_hint=query_hint)
                        except Exception as tool_err:
                            logger.warning(f"Diffy MCP tool '{name}' failed: {tool_err}")
                            results[idx] = f"TOOL_ERROR ({name}): {tool_err}"
                    self._last_error = None
                    return [r or "" for r in results]
            else:
                bridge = self.get_bridge()
                for idx in uncached_indices:
                    name, args = tool_calls[idx]
                    normalized_args = args or {}
                    try:
                        res = await bridge.call_tool(name, normalized_args)
                        raw_text = res if isinstance(res, str) else json.dumps(res, ensure_ascii=False)
                        if name == "list_skills":
                            parsed = _parse_skills_catalog(raw_text)
                            if parsed:
                                self._cached_skills = parsed
                                self._cached_raw_skills_text = raw_text
                                self._last_success_ts = time.monotonic()
                        if self._is_cacheable_result(name, raw_text):
                            cache_key = (
                                name,
                                json.dumps(normalized_args, sort_keys=True, ensure_ascii=False),
                            )
                            self._tool_result_cache[cache_key] = (time.monotonic(), raw_text)
                        normalized = self._normalize_tool_output(name, raw_text)
                        results[idx] = _compact_markdown_for_voice(normalized, query_hint=query_hint)
                    except Exception as tool_err:
                        logger.warning(f"Diffy MCP tool '{name}' failed: {tool_err}")
                        results[idx] = f"TOOL_ERROR ({name}): {tool_err}"
                self._last_error = None
                return [r or "" for r in results]
        except Exception as conn_err:
            self._last_failure_ts = time.monotonic()
            self._last_error = str(conn_err)
            logger.warning(f"Diffy MCP batch connection failed: {conn_err}")
            fallback_msg = (
                f"MCP_UNAVAILABLE: Diffy MCP server could not be reached ({conn_err}). "
                + (
                    "Hybrid Mode fallback: answer concisely using general knowledge."
                    if self.settings.mcp_mode == "hybrid"
                    else "Report unavailability cleanly."
                )
            )
            for idx in uncached_indices:
                results[idx] = fallback_msg
            return [r or "" for r in results]

    async def get_status(self) -> Dict[str, Any]:
        """Return current Diffy MCP status and cached skill statistics."""
        cache_stats = {
            "cached_skill_entries": len(self._tool_result_cache),
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
        }
        if not self.is_active:
            return {
                "enabled": bool(self.settings.mcp_enabled),
                "mode": self.settings.mcp_mode,
                "server_url": self.settings.mcp_server_url,
                "connected": False,
                "tools": [],
                "skills_count": 0,
                "last_error": "disabled",
                **cache_stats,
            }

        connected = await self._refresh_cache_if_needed(force=False)
        # Re-check freshness after potential failed fallback to stale cache
        fresh = self._last_error is None and connected
        return {
            "enabled": bool(self.settings.mcp_enabled),
            "mode": self.settings.mcp_mode,
            "server_url": self.settings.mcp_server_url,
            "connected": fresh,
            "tools": list(self._cached_tool_names),
            "skills_count": len(self._cached_skills),
            "last_error": self._last_error,
            **cache_stats,
        }


_mcp_client_instance: Optional[MCPSkillsClient] = None


def get_mcp_skills_client() -> MCPSkillsClient:
    """Singleton getter for MCPSkillsClient."""
    global _mcp_client_instance
    if _mcp_client_instance is None:
        _mcp_client_instance = MCPSkillsClient()
    return _mcp_client_instance
