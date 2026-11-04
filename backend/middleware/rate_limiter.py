import time
import logging
from typing import Dict, List
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.config.settings import get_settings

logger = logging.getLogger("ai_voice_assistant.rate_limiter")


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """In-memory sliding-window rate limiter per client IP."""

    def __init__(self, app):
        super().__init__(app)
        self._ip_history: Dict[str, List[float]] = {}
        self.settings = get_settings()

    async def dispatch(self, request: Request, call_next):
        # Exclude static files and health check
        path = request.url.path
        if path.startswith("/static") or path.startswith("/health") or path == "/":
            return await call_next(request)

        client_ip = request.client.host if request.client else "127.0.0.1"
        now = time.time()
        window_seconds = 60.0
        limit = self.settings.rate_limit_per_minute

        # Retrieve and prune old request timestamps
        timestamps = self._ip_history.get(client_ip, [])
        timestamps = [ts for ts in timestamps if now - ts < window_seconds]

        if len(timestamps) >= limit:
            logger.warning(f"Rate limit exceeded for IP [{client_ip}]: {len(timestamps)} reqs in {window_seconds}s")
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "error": "Rate limit exceeded. Please wait a moment before sending more requests.",
                    "code": "RATE_LIMIT_EXCEEDED",
                    "retry_after_seconds": int(window_seconds - (now - timestamps[0])),
                },
            )

        timestamps.append(now)
        self._ip_history[client_ip] = timestamps

        return await call_next(request)
