"""
Supply-chain-safe loading of the third-party AI models (no remote code, pinned versions, verified weights).

Before: DINOv2 came from `torch.hub.load("facebookresearch/dinov2", trust_repo=True)`, which downloads and
EXECUTES the latest code from GitHub at runtime; CLIP and Whisper downloaded whatever the Hub served.
Now:
  - DINOv2 code is vendored in backend/vendor/dinov2_hub (Apache-2.0) and loaded with source="local";
    weights are loaded with torch.load(weights_only=True) only after their SHA-256 matches the pinned value;
  - CLIP is pinned to a Hub revision and read from the local cache;
  - Whisper is read from the local cache;
  - nothing is downloaded unless ALLOW_MODEL_DOWNLOADS=true (use it once while building the server image).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.core.config import settings

VENDOR_DINOV2 = Path(__file__).resolve().parents[2] / "vendor" / "dinov2_hub"
DINOV2_WEIGHTS_SHA256 = "b938bf1bc15cd2ec0feacfe3a1bb553fe8ea9ca46a7e1d8d00217f29aef60cd9"
DINOV2_WEIGHTS_URL = "https://dl.fbaipublicfiles.com/dinov2/dinov2_vits14/dinov2_vits14_pretrain.pth"
CLIP_REVISION = "57c216476eefef5ab752ec549e440a49ae4ae5f3"        # openai/clip-vit-base-patch16
WHISPER_BASE_REVISION = "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66"  # Systran/faster-whisper-base


class ModelIntegrityError(RuntimeError):
    """A model file is missing or does not match its pinned checksum."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dinov2_weights_path() -> Path:
    import torch

    path = Path(settings.dinov2_weights_path) if settings.dinov2_weights_path else Path(torch.hub.get_dir()) / "checkpoints" / "dinov2_vits14_pretrain.pth"
    if not path.exists():
        if not settings.allow_model_downloads:
            raise ModelIntegrityError(f"DINOv2 weights not found at {path}; set ALLOW_MODEL_DOWNLOADS=true once to fetch them")
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.hub.download_url_to_file(DINOV2_WEIGHTS_URL, str(path), hash_prefix=DINOV2_WEIGHTS_SHA256[:10])
    if _sha256(path) != DINOV2_WEIGHTS_SHA256:
        raise ModelIntegrityError(f"DINOv2 weights at {path} do not match the pinned SHA-256; refusing to load")
    return path


def load_dinov2_vits14():
    import torch

    model = torch.hub.load(str(VENDOR_DINOV2), "dinov2_vits14", source="local", pretrained=False)
    state = torch.load(dinov2_weights_path(), map_location="cpu", weights_only=True)
    model.load_state_dict(state)
    return model


def load_clip(model_id: str):
    from transformers import CLIPModel, CLIPProcessor

    if not settings.allow_model_downloads:   # audit L-07: also stops transformers' background hub checks
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    kwargs = {"revision": CLIP_REVISION, "local_files_only": not settings.allow_model_downloads}
    return CLIPModel.from_pretrained(model_id, **kwargs), CLIPProcessor.from_pretrained(model_id, **kwargs)  # nosec B615 - revision pinned


def load_whisper(size: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel

    if not settings.allow_model_downloads:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    return WhisperModel(size, device=device, compute_type=compute_type, local_files_only=not settings.allow_model_downloads)
