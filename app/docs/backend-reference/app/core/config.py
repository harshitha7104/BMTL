"""
Application configuration using environment variables.
"""
from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "ScrapTrust Assessment API"
    app_version: str = "1.0.0-mvp"
    debug: bool = False

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_timeout: int = 60
    openai_max_retries: int = 3

    # Upload limits
    max_upload_size_mb: int = 10
    max_images_per_assessment: int = 5
    allowed_image_types: List[str] = ["image/jpeg", "image/png", "image/webp"]

    # Storage
    storage_type: str = "local"  # "local" | "postgres" | "s3"
    local_storage_path: str = "./data"
    database_url: str = ""
    s3_bucket: str = ""
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""

    # Security
    cors_origins: List[str] = ["http://localhost:3000", "http://localhost:5173"]
    rate_limit_per_minute: int = 30
    secret_key: str = "change-me-in-production"

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


settings = Settings()
