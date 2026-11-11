import asyncio
import hashlib
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import List, Dict, Optional, Any, AsyncGenerator, Tuple
from google import genai
from google.genai import types
from google.genai.errors import APIError

from backend.config.settings import get_settings, Settings
from backend.ai.mcp_client import MCPSkillsClient, get_mcp_skills_client

logger = logging.getLogger("ai_voice_assistant.gemini")

VOLATILE_QUERY_PATTERN = re.compile(
    r"\b(time|date|today|tomorrow|yesterday|now|weather|current|latest|remember|previous|last|earlier)\b",
    re.IGNORECASE,
)


@dataclass
class ModelCircuitState:
    """Tracks failure counts and cooldown window for a single Gemini model."""

    consecutive_failures: int = 0
    opened_until: float = 0.0
    total_failures: int = 0
    total_successes: int = 0
    last_error: Optional[str] = None


class GeminiService:
    """Service wrapper for Google Gemini AI with streaming, fallback models, circuit breaker, MCP tools, and Q&A cache."""

    CIRCUIT_FAILURE_THRESHOLD = 2
    CIRCUIT_COOLDOWN_SECONDS = 60.0
    RESPONSE_CACHE_TTL_SECONDS = 120.0
    RESPONSE_CACHE_MAX_ENTRIES = 64

    def __init__(
        self,
        settings: Optional[Settings] = None,
        mcp_client: Optional[MCPSkillsClient] = None,
    ):
        self.settings = settings or get_settings()
        self.mcp_client = mcp_client if mcp_client is not None else get_mcp_skills_client()
        self._client: Optional[genai.Client] = None
        self._last_key: str = ""
        self._circuits: Dict[str, ModelCircuitState] = {}
        self._response_cache: OrderedDict[str, Tuple[float, str]] = OrderedDict()
        self._cache_hits: int = 0
        self._cache_misses: int = 0

    def _get_client(self) -> genai.Client:
        """Lazily initialize or refresh the Gemini client if API key changed."""
        current_key = self.settings.gemini_api_key.strip()
        if not current_key or current_key == "your_gemini_api_key_here":
            raise ValueError(
                "Gemini API key is not configured. Please set GEMINI_API_KEY in your .env file."
            )

        if self._client is None or self._last_key != current_key:
            logger.info("Initializing Google GenAI Client with configured API key.")
            self._client = genai.Client(api_key=current_key)
            self._last_key = current_key

        return self._client

    def _get_circuit(self, model_name: str) -> ModelCircuitState:
        if model_name not in self._circuits:
            self._circuits[model_name] = ModelCircuitState()
        return self._circuits[model_name]

    def _is_circuit_open(self, model_name: str, now: Optional[float] = None) -> bool:
        circuit = self._circuits.get(model_name)
        if circuit is None or circuit.opened_until <= 0:
            return False
        ts = time.monotonic() if now is None else now
        return ts < circuit.opened_until

    def _record_model_success(self, model_name: str) -> None:
        circuit = self._get_circuit(model_name)
        circuit.consecutive_failures = 0
        circuit.opened_until = 0.0
        circuit.total_successes += 1
        circuit.last_error = None

    def _record_model_failure(self, model_name: str, err: Exception) -> None:
        circuit = self._get_circuit(model_name)
        circuit.consecutive_failures += 1
        circuit.total_failures += 1
        circuit.last_error = str(err)
        if circuit.consecutive_failures >= self.CIRCUIT_FAILURE_THRESHOLD:
            circuit.opened_until = time.monotonic() + self.CIRCUIT_COOLDOWN_SECONDS
            logger.warning(
                f"Circuit breaker OPENED for model [{model_name}] for {self.CIRCUIT_COOLDOWN_SECONDS:.0f}s "
                f"after {circuit.consecutive_failures} consecutive failures."
            )

    def _ordered_models_for_request(self, candidates: List[str]) -> List[str]:
        """Prioritize healthy/half-open models and skip currently open circuits unless all are tripped."""
        now = time.monotonic()
        healthy = [m for m in candidates if not self._is_circuit_open(m, now)]
        return healthy if healthy else list(candidates)

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return Gemini circuit breaker and Q&A cache telemetry."""
        now = time.monotonic()
        circuits_view: Dict[str, Dict[str, Any]] = {}
        for name, st in self._circuits.items():
            remaining = max(0.0, st.opened_until - now) if st.opened_until > 0 else 0.0
            state_label = "open" if remaining > 0 else ("half_open" if st.consecutive_failures > 0 else "closed")
            circuits_view[name] = {
                "state": state_label,
                "consecutive_failures": st.consecutive_failures,
                "cooldown_remaining_s": round(remaining, 1),
                "total_successes": st.total_successes,
                "total_failures": st.total_failures,
                "last_error": st.last_error,
            }
        return {
            "active_model": self.settings.gemini_model,
            "response_cache_entries": len(self._response_cache),
            "response_cache_hits": self._cache_hits,
            "response_cache_misses": self._cache_misses,
            "circuits": circuits_view,
        }

    def _make_cache_key(
        self,
        prompt: str,
        effective_instruction: str,
        mcp_active: bool,
        model_override: Optional[str],
    ) -> str:
        normalized = " ".join(prompt.lower().split())
        instr_hash = hashlib.sha256(effective_instruction.encode("utf-8")).hexdigest()[:12]
        raw = f"{normalized}|{self.settings.mcp_mode}|{mcp_active}|{model_override or ''}|{instr_hash}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _is_cacheable_prompt(self, prompt: str, history: Optional[List[Dict[str, str]]]) -> bool:
        if history:
            return False
        if len(prompt.strip()) > 220:
            return False
        if VOLATILE_QUERY_PATTERN.search(prompt):
            return False
        return True

    def _get_cached_response(self, cache_key: str) -> Optional[str]:
        entry = self._response_cache.get(cache_key)
        if not entry:
            return None
        ts, text = entry
        if (time.monotonic() - ts) >= self.RESPONSE_CACHE_TTL_SECONDS:
            self._response_cache.pop(cache_key, None)
            return None
        self._response_cache.move_to_end(cache_key)
        return text

    def _store_cached_response(self, cache_key: str, text: str) -> None:
        if not text or text.startswith(("Sorry,", "I'm sorry,", "⚠️")):
            return
        self._response_cache[cache_key] = (time.monotonic(), text)
        self._response_cache.move_to_end(cache_key)
        while len(self._response_cache) > self.RESPONSE_CACHE_MAX_ENTRIES:
            self._response_cache.popitem(last=False)

    def _build_contents_and_config(
        self,
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        custom_system_instruction: Optional[str] = None,
        tools: Optional[List[types.Tool]] = None,
    ) -> Tuple[List[types.Content], types.GenerateContentConfig]:
        """Prepare messages and configuration for Google GenAI SDK."""
        system_instruction = custom_system_instruction or self.settings.system_instruction
        contents: List[types.Content] = []
        if history:
            for item in history:
                role = "user" if item.get("role") == "user" else "model"
                text = item.get("text", "").strip()
                if text:
                    contents.append(
                        types.Content(
                            role=role,
                            parts=[types.Part.from_text(text=text)],
                        )
                    )

        contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=prompt.strip())],
            )
        )

        config_kwargs: Dict[str, Any] = {
            "system_instruction": system_instruction,
            "temperature": 0.7,
            "max_output_tokens": 400,
            "http_options": types.HttpOptions(timeout=15000),
        }
        if tools:
            config_kwargs["tools"] = tools

        config = types.GenerateContentConfig(**config_kwargs)
        return contents, config

    async def verify_connection(self) -> Dict[str, Any]:
        """Test API key validity and model connectivity."""
        if not self.settings.has_api_key:
            return {
                "status": "missing_key",
                "message": "Gemini API key is not configured in .env",
                "model": self.settings.gemini_model,
            }

        client = self._get_client()
        models_to_check = [
            self.settings.gemini_model,
            "gemini-flash-lite-latest",
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash-lite",
        ]
        unique_models = list(dict.fromkeys(models_to_check))
        last_error = None

        for m_name in unique_models:
            try:
                def _ping(target_model=m_name):
                    response = client.models.generate_content(
                        model=target_model,
                        contents="Reply with 'ready'.",
                        config=types.GenerateContentConfig(
                            max_output_tokens=10,
                            temperature=0.0,
                            http_options=types.HttpOptions(timeout=10000),
                        ),
                    )
                    return response.text

                res = await asyncio.wait_for(asyncio.to_thread(_ping), timeout=12.0)
                if m_name != self.settings.gemini_model:
                    logger.info(f"Auto-switched model to active working model: {m_name}")
                    self.settings.gemini_model = m_name

                logger.info(f"Gemini connection verified with model [{m_name}]: {res.strip() if res else 'OK'}")
                return {
                    "status": "connected",
                    "message": "Gemini API connected successfully.",
                    "model": m_name,
                }
            except Exception as e:
                last_error = e
                logger.warning(f"Connection check failed on {m_name}: {e}. Trying next...")
                continue

        logger.error(f"Gemini API error during connection check: {last_error}")
        return {
            "status": "api_error",
            "message": f"Gemini API error: {str(last_error)}",
            "model": self.settings.gemini_model,
        }

    async def _run_model_tool_loop(
        self,
        client: genai.Client,
        model_name: str,
        base_contents: List[types.Content],
        config: types.GenerateContentConfig,
        mcp_active: bool,
        user_prompt: str = "",
    ) -> Tuple[str, List[str]]:
        """Execute Gemini generation with optional multi-turn Diffy MCP tool calls."""
        current_contents = list(base_contents)
        tools_called: List[str] = []
        max_turns = max(1, int(getattr(self.settings, "mcp_max_tool_turns", 4)))

        def _invoke(step_contents: List[types.Content], step_config: types.GenerateContentConfig):
            return client.models.generate_content(
                model=model_name,
                contents=step_contents,
                config=step_config,
            )

        for _turn in range(max_turns):
            response = await asyncio.wait_for(
                asyncio.to_thread(_invoke, current_contents, config),
                timeout=17.0,
            )
            fn_calls = getattr(response, "function_calls", None) or []

            if not fn_calls or not mcp_active:
                text = response.text.strip() if response and response.text else ""
                if not text:
                    return "I'm sorry, I couldn't generate a response.", tools_called
                return text, tools_called

            if getattr(response, "candidates", None) and response.candidates[0].content:
                current_contents.append(response.candidates[0].content)

            batch = [(fc.name, dict(fc.args or {})) for fc in fn_calls]
            tools_called.extend(name for name, _ in batch)
            logger.info(f"Gemini invoking Diffy MCP tools: {batch}")

            tool_results = await self.mcp_client.call_tools_batch(batch, query_hint=user_prompt)
            fn_response_parts = [
                types.Part.from_function_response(name=name, response={"result": result_text})
                for (name, _), result_text in zip(batch, tool_results)
            ]
            current_contents.append(types.Content(role="user", parts=fn_response_parts))

        # Final synthesis without tools if tool-turn budget was exhausted
        final_config = types.GenerateContentConfig(
            system_instruction=config.system_instruction,
            temperature=config.temperature,
            max_output_tokens=config.max_output_tokens,
            http_options=types.HttpOptions(timeout=15000),
        )
        final_resp = await asyncio.wait_for(
            asyncio.to_thread(_invoke, current_contents, final_config),
            timeout=17.0,
        )
        final_text = final_resp.text.strip() if final_resp and final_resp.text else ""
        return (final_text or "I'm sorry, I couldn't generate a response."), tools_called

    async def generate_response(
        self,
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        custom_system_instruction: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> Tuple[str, float]:
        """Generate complete response and return (response_text, latency_ms)."""
        start_time = time.perf_counter()
        if not prompt or not prompt.strip():
            return "I didn't catch that. Could you please say or type something?", 0.0

        if not self.settings.has_api_key:
            return (
                "⚠️ Gemini API Key is missing. Please add your GEMINI_API_KEY in the .env file "
                "to enable AI responses.",
                0.0,
            )

        client = self._get_client()
        base_instruction = custom_system_instruction or self.settings.system_instruction
        mcp_tool, effective_instruction, mcp_meta = await self.mcp_client.prepare_prompt_context(
            base_instruction
        )
        mcp_active = bool(mcp_meta.get("mcp_active"))

        cache_key: Optional[str] = None
        if self._is_cacheable_prompt(prompt, history):
            cache_key = self._make_cache_key(prompt, effective_instruction, mcp_active, model_override)
            cached_text = self._get_cached_response(cache_key)
            if cached_text is not None:
                self._cache_hits += 1
                latency_ms = (time.perf_counter() - start_time) * 1000
                logger.info(f"Semantic Q&A cache HIT in {latency_ms:.2f}ms for prompt preview={prompt[:40]!r}")
                return cached_text, latency_ms
            self._cache_misses += 1

        tools_list = [mcp_tool] if mcp_tool is not None else None
        contents, config = self._build_contents_and_config(
            prompt,
            history,
            custom_system_instruction=effective_instruction,
            tools=tools_list,
        )

        models_to_try = [
            model_override or self.settings.gemini_model,
            self.settings.gemini_model,
            "gemini-flash-lite-latest",
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash-lite",
        ]
        unique_models = list(dict.fromkeys(m for m in models_to_try if m))
        ordered_models = self._ordered_models_for_request(unique_models)
        last_err: Optional[Exception] = None

        for model_name in ordered_models:
            try:
                response_text, tools_used = await self._run_model_tool_loop(
                    client=client,
                    model_name=model_name,
                    base_contents=contents,
                    config=config,
                    mcp_active=mcp_active,
                    user_prompt=prompt,
                )
                self._record_model_success(model_name)
                if cache_key is not None:
                    self._store_cached_response(cache_key, response_text)
                latency_ms = (time.perf_counter() - start_time) * 1000
                logger.info(
                    f"Gemini response generated in {latency_ms:.1f}ms using {model_name} "
                    f"(mcp_active={mcp_active}, mcp_tools={tools_used})"
                )
                return response_text, latency_ms
            except APIError as e:
                logger.warning(f"APIError with model {model_name}: {e}. Trying fallback...")
                last_err = e
                if "API_KEY_INVALID" in str(e):
                    break
                self._record_model_failure(model_name, e)
                continue
            except Exception as e:
                logger.error(f"Error with model {model_name}: {e}")
                last_err = e
                if "API_KEY_INVALID" in str(e):
                    break
                self._record_model_failure(model_name, e)
                continue

        latency_ms = (time.perf_counter() - start_time) * 1000
        return f"Sorry, I encountered an error communicating with Gemini AI: {str(last_err)}", latency_ms

    async def generate_response_stream(
        self,
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        custom_system_instruction: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream response chunks asynchronously from Gemini, supporting Diffy MCP tool calls."""
        if not prompt or not prompt.strip():
            yield "I didn't catch that. Could you please say something?"
            return

        if not self.settings.has_api_key:
            yield "⚠️ Gemini API Key is missing. Please add your GEMINI_API_KEY in the .env file."
            return

        client = self._get_client()
        base_instruction = custom_system_instruction or self.settings.system_instruction
        mcp_tool, effective_instruction, mcp_meta = await self.mcp_client.prepare_prompt_context(
            base_instruction
        )

        # When Diffy MCP tools are active, resolve tool calls cleanly before yielding text
        if mcp_tool is not None and mcp_meta.get("mcp_active"):
            text, _latency = await self.generate_response(
                prompt=prompt,
                history=history,
                custom_system_instruction=custom_system_instruction,
            )
            yield text
            return

        contents, config = self._build_contents_and_config(prompt, history, effective_instruction)
        stream_model = self._ordered_models_for_request(
            [self.settings.gemini_model, "gemini-flash-lite-latest", "gemini-3.5-flash"]
        )[0]

        def _sync_stream():
            try:
                response = client.models.generate_content_stream(
                    model=stream_model,
                    contents=contents,
                    config=config,
                )
                for chunk in response:
                    if chunk.text:
                        yield chunk.text
            except Exception as err:
                logger.error(f"Error in Gemini streaming generator: {err}")
                yield f" [Error: {str(err)}]"

        # Consume synchronous generator in non-blocking thread loop
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _worker():
            try:
                for token in _sync_stream():
                    loop.call_soon_threadsafe(queue.put_nowait, token)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        asyncio.create_task(asyncio.to_thread(_worker))

        while True:
            item = await queue.get()
            if item is None:
                break
            yield item


_gemini_service_instance: Optional[GeminiService] = None


def get_gemini_service() -> GeminiService:
    """Singleton getter for GeminiService."""
    global _gemini_service_instance
    if _gemini_service_instance is None:
        _gemini_service_instance = GeminiService()
    return _gemini_service_instance
