"""
ScrapTrust Assessment API — FastAPI Application Entry Point

This is the main entry point for the backend API server.
Run with: uvicorn app.main:app --reload --port 8000
"""
import logging
import threading
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from PIL import Image as _PILImage
from fastapi.staticfiles import StaticFiles

from app.core.config import REPO_ROOT, settings
from app.core.exceptions import register_exception_handlers
from app.api.routes import auth, health, assessments, feedback, copilot, library, admin_records
from app.core.middleware import EarlyGuard, SecurityMiddleware
from app.core.security import current_user, require_role, startup_security_check
from app.providers.registry import provider_registry
from app.repositories.local_repository import LocalRepository

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
_PILImage.MAX_IMAGE_PIXELS = 50_000_000   # hard decompression-bomb limit for every image the server decodes


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler — startup and shutdown."""
    # Startup
    startup_security_check()   # refuses to start with a default SECRET_KEY or an unsafe auth mode
    from app.records.store import get_records

    if get_records().log(None, "server_start", summary="server started") is None:   # audit M-02: never run without the audit trail
        raise RuntimeError(f"The records database is not writable: {settings.records_path} (set RECORDS_FILE to a writable volume)")
    try:
        from app.core.db import prune
        prune(settings.users_path.with_name("security.db"))   # drop expired rate-limit events
    except Exception as exc:   # housekeeping must not block startup
        logger.warning("security db housekeeping skipped: %s", exc)
    logger.info(f"Starting {settings.app_name} v{settings.app_version} (auth: {settings.auth_mode})")
    logger.info(f"AI Provider: {settings.ai_provider}")
    logger.info(f"Storage: {settings.storage_type}")

    # Initialize AI provider
    await provider_registry.initialize(settings.ai_provider)
    active_provider = provider_registry.get_active_provider()
    if active_provider:
        logger.info(f"Active AI provider: {active_provider.get_display_name()}")
    else:
        logger.warning("No AI provider available — assessments will fail")

    # Initialize storage
    repository = LocalRepository(settings.local_storage_path)
    await repository.initialize()
    logger.info(f"Storage initialized at {settings.local_storage_path}")

    # Load the Copilot's vision models in the background so the first photo answers quickly.
    if settings.copilot_warmup:
        threading.Thread(target=copilot.warm_up_engines, name="copilot-warmup", daemon=True).start()

    yield

    # Shutdown
    logger.info("Shutting down application")
    await repository.close()


class WebAppFiles(StaticFiles):
    """Static web app: HTML is always revalidated (so updates show up immediately), while
    content-hashed files under /assets are cached for a long time."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if path.replace("\\", "/").startswith("assets/"):  # Starlette uses OS separators
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response


def create_app() -> FastAPI:
    """Application factory."""
    app = FastAPI(
        title=settings.app_name,
        description="AI-powered scrap material evidence assessment and trust reporting",
        version=settings.app_version,
        docs_url="/docs" if settings.expose_api_docs else None,
        redoc_url="/redoc" if settings.expose_api_docs else None,
        openapi_url="/openapi.json" if settings.expose_api_docs else None,
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.add_middleware(SecurityMiddleware)
    hosts = [h.strip() for h in settings.trusted_hosts.split(",") if h.strip()]
    if hosts:   # answer only to our own host names (Host-header poisoning, DNS rebinding against the API)
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts + ["127.0.0.1", "localhost"])   # + container health checks
    app.add_middleware(EarlyGuard)   # added last = runs first: host allow-list, early 401, streamed size cap (audit H-01, M-01)

    # Register exception handlers
    register_exception_handlers(app)

    # Register routes
    signed_in = [Depends(current_user)]   # every API route below requires a signed-in user
    app.include_router(health.router, tags=["Health"])
    app.include_router(auth.router, prefix="/api/v1", tags=["Auth"])
    app.include_router(assessments.router, prefix="/api/v1", tags=["Assessments"], dependencies=signed_in)
    app.include_router(feedback.router, prefix="/api/v1", tags=["Feedback"], dependencies=signed_in)
    app.include_router(copilot.router, prefix="/api/v1", tags=["Copilot"], dependencies=signed_in)
    app.include_router(library.router, prefix="/api/v1", tags=["Library"], dependencies=signed_in)
    # admin only: the end-to-end activity log, observations and self-learning status (never visible to end users)
    app.include_router(admin_records.router, prefix="/api/v1", tags=["Admin records"], dependencies=[Depends(admin_records.records_access)])

    # Serve the built web app (npm run build -> <repo>/dist) from the same server, so the
    # whole product runs as one process. Mounted last: API routes above take precedence.
    web_dist = REPO_ROOT / "dist"
    if (web_dist / "index.html").exists():
        app.mount("/", WebAppFiles(directory=web_dist, html=True), name="web")
        logger.info(f"Serving web app from {web_dist}")

    return app


# Create the application instance
app = create_app()
