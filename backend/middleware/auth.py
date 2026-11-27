import hmac
import logging
from typing import Optional
from fastapi import Depends, HTTPException, Request, status

from backend.ai.agent_client import get_agent_gateway_client
from backend.config.settings import Settings, get_settings

logger = logging.getLogger("ai_voice_assistant.auth")


def _extract_api_key(request: Request) -> str:
    """Extract device token / API key from X-Device-Token, X-API-Key, Bearer auth, or api_key query param."""
    dev_tok = request.headers.get("X-Device-Token") or request.headers.get("x-device-token")
    if dev_tok:
        return dev_tok.strip()

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
    """Verify per-device paired token (`fluai_dev_...`) via Agent API or fallback shared DEVICE_API_KEY."""
    provided = _extract_api_key(request)

    if provided.startswith("fluai_dev_"):
        resolved = await get_agent_gateway_client().resolve_device_token(provided)
        if resolved:
            request.state.device_token = provided
            request.state.user_id = resolved.get("user_id")
            request.state.device_id = resolved.get("device_id")
            return provided
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked per-device pairing token.",
        )

    expected = (settings.device_api_key or "").strip()
    if not expected:
        return None

    if not provided or not hmac.compare_digest(provided, expected):
        logger.warning(f"Unauthorized request blocked on {request.url.path}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Provide X-Device-Token or X-API-Key header.",
        )
    return provided

