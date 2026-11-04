import time
import uuid
import json
import logging
from typing import Optional, Dict, Any
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("ai_voice_assistant.metrics")


class RequestTracingMiddleware(BaseHTTPMiddleware):
    """Middleware attaching unique Request ID and tracking end-to-end request duration."""

    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:8]}"
        request.state.trace_id = trace_id
        start_time = time.perf_counter()

        response = await call_next(request)

        duration_ms = (time.perf_counter() - start_time) * 1000
        response.headers["X-Request-ID"] = trace_id
        response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"

        # Structured request log
        if not request.url.path.startswith("/static"):
            logger.info(
                f"[{trace_id}] {request.method} {request.url.path} -> {response.status_code} ({duration_ms:.1f}ms)"
            )

        return response


def log_pipeline_metrics(
    trace_id: str,
    session_id: str,
    stt_duration_ms: float = 0.0,
    gemini_latency_ms: float = 0.0,
    tts_latency_ms: float = 0.0,
    total_duration_ms: float = 0.0,
    model: str = "",
    voice: str = "",
    language: str = "",
    state: str = "IDLE",
    error: Optional[str] = None,
) -> None:
    """Log structured performance metrics safely without exposing credentials."""
    metrics: Dict[str, Any] = {
        "event": "voice_pipeline_metrics",
        "trace_id": trace_id,
        "session_id": session_id,
        "stt_duration_ms": round(stt_duration_ms, 1),
        "gemini_latency_ms": round(gemini_latency_ms, 1),
        "tts_latency_ms": round(tts_latency_ms, 1),
        "total_duration_ms": round(total_duration_ms, 1),
        "model": model,
        "voice": voice,
        "language": language,
        "state": state,
    }
    if error:
        metrics["error"] = error

    logger.info(json.dumps(metrics))
