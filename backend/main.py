import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.config.settings import get_settings
from backend.api.routes import router as api_router
from backend.api.websocket import ws_router
from backend.middleware.observability import RequestTracingMiddleware
from backend.middleware.rate_limiter import RateLimiterMiddleware
from backend.voice.text_to_speech import TEMP_AUDIO_DIR

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ai_voice_assistant")

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle management."""
    settings = get_settings()
    logger.info("==================================================")
    logger.info("  🚀 Starting AI Voice Assistant Backend Server")
    logger.info(f"  🤖 Model: {settings.gemini_model}")
    logger.info(f"  🔑 API Key Configured: {settings.has_api_key}")
    logger.info(f"  🔊 TTS Voice: {settings.tts_voice}")
    logger.info(f"  🌐 Host: {settings.host}:{settings.port}")
    logger.info(f"  🛡️ Rate Limit: {settings.rate_limit_per_minute} req/min")
    logger.info("==================================================")

    # Ensure audio temp dir exists
    TEMP_AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    yield

    logger.info("🛑 Shutting down AI Voice Assistant Backend.")


def create_app() -> FastAPI:
    """FastAPI Application Factory."""
    settings = get_settings()

    app = FastAPI(
        title="Aether AI Voice Assistant API",
        description="Production-grade Voice Assistant API for Physical and Web AI Devices",
        version="1.0.0",
        lifespan=lifespan,
    )

    # 1. Observability & Tracing Middleware
    app.add_middleware(RequestTracingMiddleware)

    # 2. Rate Limiting Middleware
    app.add_middleware(RateLimiterMiddleware)

    # 3. CORS Middleware with Configurable Origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins if not settings.debug else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 4. Include REST & WebSocket Routes
    app.include_router(api_router)
    app.include_router(ws_router)

    # 5. Mount frontend static files
    if FRONTEND_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

        @app.get("/", include_in_schema=False)
        async def serve_index():
            index_path = FRONTEND_DIR / "index.html"
            if index_path.exists():
                return FileResponse(str(index_path))
            return {"message": "Frontend index.html not found"}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
