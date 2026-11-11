import hmac
import logging
from typing import Optional
from fastapi import Depends, HTTPException, Request, status

from backend.config.settings import Settings, get_settings

logger = logging.getLogger("ai_voice_assistant.auth")


def _extract_api_key(request: Request) -> str:
    """Extract device API key from X-API-Key header, Bearer auth, or api_key query param."""
    direct = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if direct:
        return direct.strip()

    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()

    query_key = request.query_params.get("api_key")
    if query_key:
        return query_key.strip()

    return ""


async def verify_device_api_key(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> Optional[str]:
    """Enforce X-API-Key authentication on protected endpoints when DEVICE_API_KEY is configured."""
    expected = (settings.device_api_key or "").strip()
    if not expected:
        return None

    provided = _extract_api_key(request)
    if not provided or not hmac.compare_digest(provided, expected):
        logger.warning(f"Unauthorized request blocked on {request.url.path}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Provide X-API-Key header.",
        )
    return provided

