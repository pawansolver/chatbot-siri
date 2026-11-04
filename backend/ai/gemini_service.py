import asyncio
import time
import logging
from typing import List, Dict, Optional, Any, AsyncGenerator, Tuple
from google import genai
from google.genai import types
from google.genai.errors import APIError

from backend.config.settings import get_settings, Settings

logger = logging.getLogger("ai_voice_assistant.gemini")


class GeminiService:
    """Service wrapper for Google Gemini AI with streaming, fallback models, and latency tracking."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._client: Optional[genai.Client] = None
        self._last_key: str = ""

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

    def _build_contents_and_config(
        self,
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        custom_system_instruction: Optional[str] = None,
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

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.7,
            max_output_tokens=400,
        )
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
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash-lite",
            "gemini-3.8-flash",
            "gemini-flash-latest",
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
                        ),
                    )
                    return response.text

                res = await asyncio.to_thread(_ping)
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

    async def generate_response(
        self,
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        custom_system_instruction: Optional[str] = None,
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
        contents, config = self._build_contents_and_config(prompt, history, custom_system_instruction)

        models_to_try = [
            self.settings.gemini_model,
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash-lite",
            "gemini-3.8-flash",
            "gemini-flash-latest",
        ]
        unique_models = list(dict.fromkeys(models_to_try))
        last_err: Optional[Exception] = None

        def _call_gemini(model_name: str) -> str:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
            if response and response.text:
                return response.text.strip()
            return "I'm sorry, I couldn't generate a response."

        for model_name in unique_models:
            try:
                response_text = await asyncio.to_thread(_call_gemini, model_name)
                latency_ms = (time.perf_counter() - start_time) * 1000
                logger.info(f"Gemini response generated in {latency_ms:.1f}ms using {model_name}")
                return response_text, latency_ms
            except APIError as e:
                logger.warning(f"APIError with model {model_name}: {e}. Trying fallback...")
                last_err = e
                continue
            except Exception as e:
                logger.error(f"Error with model {model_name}: {e}")
                last_err = e
                if "API_KEY_INVALID" in str(e) or "400" in str(e):
                    break
                continue

        latency_ms = (time.perf_counter() - start_time) * 1000
        return f"Sorry, I encountered an error communicating with Gemini AI: {str(last_err)}", latency_ms

    async def generate_response_stream(
        self,
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        custom_system_instruction: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream response chunks asynchronously from Gemini for ultra-low latency UI updates."""
        if not prompt or not prompt.strip():
            yield "I didn't catch that. Could you please say something?"
            return

        if not self.settings.has_api_key:
            yield "⚠️ Gemini API Key is missing. Please add your GEMINI_API_KEY in the .env file."
            return

        client = self._get_client()
        contents, config = self._build_contents_and_config(prompt, history, custom_system_instruction)

        def _sync_stream():
            try:
                response = client.models.generate_content_stream(
                    model=self.settings.gemini_model,
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
