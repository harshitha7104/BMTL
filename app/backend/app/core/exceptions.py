"""
Custom exception hierarchy and exception handlers for FastAPI.

All exceptions map to consistent JSON error responses.
Internal details are never exposed to clients.
"""
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger(__name__)


# --- Custom Exceptions ---

class ScrapTrustError(Exception):
    """Base exception for all ScrapTrust errors."""
    def __init__(
        self,
        message: str,
        error_code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class ValidationError(ScrapTrustError):
    """Request validation failed."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            status_code=400,
            details=details,
        )


class FileTooLargeError(ScrapTrustError):
    """Uploaded file exceeds size limit."""
    def __init__(self, filename: str, size_bytes: int, max_bytes: int):
        super().__init__(
            message=f"File '{filename}' ({size_bytes} bytes) exceeds maximum size of {max_bytes} bytes",
            error_code="FILE_TOO_LARGE",
            status_code=413,
        )


class UnsupportedFormatError(ScrapTrustError):
    """File type not accepted."""
    def __init__(self, filename: str, content_type: str, allowed: list):
        super().__init__(
            message=f"File '{filename}' has unsupported type '{content_type}'. Allowed: {allowed}",
            error_code="UNSUPPORTED_FORMAT",
            status_code=400,
        )


class CorruptedFileError(ScrapTrustError):
    """File appears corrupted or unreadable."""
    def __init__(self, filename: str, reason: str = "File could not be read"):
        super().__init__(
            message=f"File '{filename}' is corrupted or unreadable: {reason}",
            error_code="CORRUPTED_FILE",
            status_code=400,
        )


class NotFoundError(ScrapTrustError):
    """Requested resource not found."""
    def __init__(self, resource: str, identifier: str):
        super().__init__(
            message=f"{resource} '{identifier}' not found",
            error_code="NOT_FOUND",
            status_code=404,
        )


class RateLimitExceededError(ScrapTrustError):
    """Too many requests."""
    def __init__(self, retry_after: int = 60):
        super().__init__(
            message=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            error_code="RATE_LIMIT_EXCEEDED",
            status_code=429,
            details={"retry_after": retry_after},
        )


class AIProviderError(ScrapTrustError):
    """AI provider encountered an error."""
    def __init__(self, message: str, error_type: str = "processing_error"):
        super().__init__(
            message=message,
            error_code="AI_PROVIDER_ERROR",
            status_code=502,
            details={"error_type": error_type},
        )


class AIProviderUnavailableError(ScrapTrustError):
    """No AI provider is available."""
    def __init__(self):
        super().__init__(
            message="No AI provider is available. Check configuration.",
            error_code="AI_PROVIDER_UNAVAILABLE",
            status_code=503,
        )


class SchemaValidationError(ScrapTrustError):
    """AI response did not match expected schema."""
    def __init__(self, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message="AI response did not match expected schema",
            error_code="SCHEMA_VALIDATION_FAILURE",
            status_code=502,
            details=details,
        )


# --- Exception Handlers ---

def register_exception_handlers(app: FastAPI) -> None:
    """Register custom exception handlers with the FastAPI app."""

    @app.exception_handler(ScrapTrustError)
    async def scrap_trust_error_handler(request: Request, exc: ScrapTrustError):
        """Handle all ScrapTrust custom exceptions."""
        logger.warning(
            f"ScrapTrustError: {exc.error_code} - {exc.message}",
            extra={"path": request.url.path},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": exc.error_code,
                "message": exc.message,
                "details": exc.details,
            },
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception):
        """Handle unexpected errors — never expose internals."""
        logger.error(
            f"Unhandled exception: {type(exc).__name__}: {str(exc)}",
            extra={"path": request.url.path},
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "INTERNAL_ERROR",
                "message": "An internal error occurred. Please try again later.",
            },
        )
