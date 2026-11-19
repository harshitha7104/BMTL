"""
Application configuration using environment variables.

All sensitive values (API keys, secrets) are loaded from environment variables.
Defaults are safe for local development without any external services.
"""
from pathlib import Path
from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> repository root
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "ScrapTrust Assessment API"
    app_version: str = "1.0.0-mvp"
    debug: bool = False
    log_level: str = "INFO"

    # AI Provider
    ai_provider: str = Field(
        default="mock",
        description="AI provider to use: 'mock' | 'openai' | 'local'",
    )

    # OpenAI (OPTIONAL — only used if ai_provider="openai")
    openai_api_key: str = Field(default="", repr=False)
    openai_model: str = "gpt-4o"
    openai_timeout: int = 60
    openai_max_retries: int = 3

    # ------------------------------------------------------------------
    # Copilot (scrap / waste / mineral assistant)
    # ------------------------------------------------------------------
    # "auto" picks the first configured provider in the order
    # claude -> openai -> gemini -> openai_compatible, else "offline".
    copilot_provider: str = Field(
        default="auto",
        description="'auto' | 'claude' | 'openai' | 'gemini' | 'openai_compatible' | 'offline'",
    )
    copilot_max_tool_rounds: int = 8
    copilot_max_media_mb: int = 200      # audio / video uploads
    copilot_warmup: bool = True          # preload vision models at startup (background thread)

    # Local speech-to-text (faster-whisper). "cpu" + "int8" is safe on any machine;
    # "cuda" + "float16" is faster on NVIDIA GPUs with cuDNN 9 installed.
    whisper_model: str = "base"          # tiny | base | small | medium | large-v3
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    # Zero-shot material identification (CLIP) for photos: names copper, brass, aluminium, ...
    material_model: str = "openai/clip-vit-base-patch16"
    material_device: str = "auto"        # auto | cuda | cpu

    # Anthropic Claude (ANTHROPIC_API_KEY is also read by the SDK directly)
    anthropic_api_key: str = Field(default="", repr=False)
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "medium"  # low | medium | high | xhigh | max

    # Google Gemini
    gemini_api_key: str = Field(default="", repr=False)
    gemini_model: str = "gemini-2.5-pro"

    # Any OpenAI-compatible endpoint (Ollama, LM Studio, vLLM, Groq, OpenRouter, Azure proxy...)
    openai_compatible_base_url: str = ""
    openai_compatible_api_key: str = Field(default="", repr=False)
    openai_compatible_model: str = ""
    openai_compatible_vision: bool = False   # True only for a vision model (e.g. qwen2.5vl); text models get tool results, not pixels

    # Data locations (empty = resolve relative to the repository root)
    embeddings_dir: str = ""          # default: <repo>/data/embeddings
    mineral_dir: str = ""             # default: <repo>/mineral
    waste_image_roots: str = ""       # comma-separated; default: <repo>/data/raw/wastes,<repo>/wastes

    # Local Vision Model (OPTIONAL — only used if ai_provider="local")
    local_model_path: str = ""
    local_model_device: str = "cpu"

    # Upload limits
    max_upload_size_mb: int = 10
    max_images_per_assessment: int = 5
    allowed_image_types: str = "image/jpeg,image/png,image/webp"

    # Storage
    storage_type: str = "local"
    local_storage_path: str = "./data"
    local_db_path: str = "./data/assessments.db"

    # Security (see app/core/security.py for the threat model)
    cors_origins: str = '[]'                   # audit L-08: same-origin app needs none; dev servers set CORS_ORIGINS in .env
    rate_limit_per_minute: int = 30            # chat turns per user per minute
    transcribe_rate_per_minute: int = 10
    link_fetch_rate_per_minute: int = 10
    secret_key: str = Field(default="change-me-in-production", repr=False)
    auth_mode: str = "required"                # "required" | "disabled_local_dev" (localhost only, never in production)
    host_binding: str = "127.0.0.1"            # the address uvicorn binds to (the launcher sets HOST_BINDING)
    users_file: str = ""                       # default: <backend>/data/security/users.json
    support_contact: str = ""                  # e.g. "scraptrust-support@company.com" or a phone/Teams channel; shown on Help
    records_file: str = ""                     # default: <backend>/data/records/records.db (activity log, library, readings)
    records_retention_days: int = 0            # 0 = keep everything (end-to-end record); >0 prunes older activity
    records_max_detail_chars: int = 200000     # cap on one logged event's structured detail
    session_ttl_hours: int = 12
    # AUTH_MODE=public_demo (open testing): no login screen; every browser gets its own private guest space
    guest_ttl_days: int = 30
    public_records: bool = False               # public_demo only: every visitor may VIEW Records (read-only, no IPs or sign-ins)                   # how long a browser keeps its guest identity (and so its chats)
    guests_per_ip_per_hour: int = 20           # new guest identities one network may create per hour
    guest_ip_chat_per_minute: int = 60         # chat messages per network per minute across all its guests
    cookie_secure: bool = False                # set true behind HTTPS (adds Secure + HSTS)
    trust_proxy_headers: bool = False          # only behind a reverse proxy you control
    login_max_failures: int = 5                # per account+IP within login_lockout_minutes
    login_lockout_minutes: int = 15
    expose_api_docs: bool = False              # /docs and /redoc are off unless explicitly enabled
    max_files_per_message: int = 20
    max_request_mb: int = 250                  # whole request body, checked before reading
    # Archives ("folders" sent as .zip or picked as a directory)
    zip_max_members: int = 200
    zip_max_total_mb: int = 300
    zip_max_ratio: int = 100                   # uncompressed / compressed, per member (zip-bomb guard)
    # Links in messages
    allow_link_fetch: bool = True
    link_max_mb: int = 15
    link_timeout_s: int = 15
    link_allowed_domains: str = ""             # comma-separated allow-list; empty = any public host
    link_blocked_domains: str = ""             # comma-separated deny-list
    # Production / scale (2026-11-17)
    redis_url: str = Field(default="", repr=False)   # set for several hosts: shared rate limits
    trusted_hosts: str = ""                    # comma-separated host names the server answers to (Host-header attacks); empty = any
    user_storage_quota_mb: int = 500           # uploads + extracted frames per user
    session_retention_days: int = 365          # conversations older than this are deleted by scripts/housekeeping.py
    heavy_job_slots: int = 4                   # concurrent transcriptions / video / OCR / PDF jobs per worker
    heavy_job_wait_s: int = 20
    allow_model_downloads: bool = False        # models load only from local, pinned, checksum-verified files
    dinov2_weights_path: str = ""              # default: torch hub cache checkpoints/dinov2_vits14_pretrain.pth                 # wait for a free slot before answering "busy, try again"

    # Feature flags
    enable_human_review: bool = True
    enable_xrf_recommendation: bool = True

    @property
    def allowed_image_types_list(self) -> List[str]:
        """Parse comma-separated allowed image types."""
        return [t.strip() for t in self.allowed_image_types.split(",") if t.strip()]

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins from JSON string."""
        import json
        try:
            return json.loads(self.cors_origins)
        except (json.JSONDecodeError, TypeError):
            return ["http://localhost:3000", "http://localhost:5173"]

    @property
    def embeddings_path(self) -> Path:
        return Path(self.embeddings_dir) if self.embeddings_dir else REPO_ROOT / "data" / "embeddings"

    @property
    def mineral_path(self) -> Path:
        return Path(self.mineral_dir) if self.mineral_dir else REPO_ROOT / "mineral"

    @property
    def waste_image_root_paths(self) -> List[Path]:
        if self.waste_image_roots:
            return [Path(p.strip()) for p in self.waste_image_roots.split(",") if p.strip()]
        return [REPO_ROOT / "data" / "raw" / "wastes", REPO_ROOT / "wastes"]

    @property
    def users_path(self) -> Path:
        return Path(self.users_file) if self.users_file else Path(__file__).resolve().parents[2] / "data" / "security" / "users.json"

    @property
    def records_path(self) -> Path:
        return Path(self.records_file) if self.records_file else Path(__file__).resolve().parents[2] / "data" / "records" / "records.db"

    @property
    def session_ttl_s(self) -> int:
        return int(self.session_ttl_hours) * 3600

    @property
    def max_upload_size_bytes(self) -> int:
        """Convert MB to bytes."""
        return self.max_upload_size_mb * 1024 * 1024


# Global settings instance
settings = Settings()

# Security audit L-07: Hugging Face libraries read these switches when they are first imported, so they must be set here,
# before any route or engine module loads transformers / huggingface_hub. With downloads off, the server makes no
# calls to huggingface.co (models load from the pinned, checksum-verified local cache only).
if not settings.allow_model_downloads:
    import os as _os

    for _var in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY"):
        _os.environ.setdefault(_var, "1")
