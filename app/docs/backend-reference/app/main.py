"""
Scrap Assessment System — FastAPI Application Entry Point
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health, assessments, feedback
from app.core.config import settings
from app.core.exceptions import register_exception_handlers


def create_app() -> FastAPI:
    """Application factory."""
    app = FastAPI(
        title="ScrapTrust Assessment API",
        description="AI-powered scrap material evidence assessment and trust reporting",
        version="1.0.0-mvp",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routes
    app.include_router(health.router, tags=["Health"])
    app.include_router(assessments.router, prefix="/api/v1", tags=["Assessments"])
    app.include_router(feedback.router, prefix="/api/v1", tags=["Feedback"])

    # Register exception handlers
    register_exception_handlers(app)

    return app


app = create_app()
