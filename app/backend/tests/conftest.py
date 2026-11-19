"""
Test configuration and fixtures.
"""
import asyncio
import io
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from PIL import Image

from app.main import app
from app.core.config import settings
from app.repositories.local_repository import LocalRepository


@pytest.fixture(autouse=True)
def isolated_records(tmp_path):
    """Every test gets its own records database; tests never touch data/records/records.db."""
    from app.records.store import RecordsStore, set_records

    store = RecordsStore(tmp_path / "records.db")
    set_records(store)
    yield store
    set_records(None)


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[AsyncClient, None]:
    """Create a test client for the API.

    ASGITransport does not trigger FastAPI lifespan events, so run the app's
    lifespan explicitly to initialize the AI provider and storage. Storage is
    redirected to a per-test temp directory.
    """
    monkeypatch.setattr(settings, "local_storage_path", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "copilot_warmup", False)  # don't load real vision models in tests
    # Functional tests run signed in as the local-dev user; tests/test_security.py covers AUTH_MODE=required.
    monkeypatch.setattr(settings, "auth_mode", "disabled_local_dev")
    monkeypatch.setattr(settings, "users_file", str(tmp_path / "security" / "users.json"))
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://localhost") as ac:
            yield ac


@pytest.fixture
def test_data_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for test data."""
    data_dir = tmp_path / "test_data"
    data_dir.mkdir()
    return data_dir


@pytest_asyncio.fixture
async def repository(test_data_dir: Path) -> AsyncGenerator[LocalRepository, None]:
    """Create a test repository."""
    repo = LocalRepository(str(test_data_dir))
    await repo.initialize()
    yield repo
    await repo.close()


@pytest.fixture
def sample_jpeg_bytes() -> bytes:
    """Create small, decodable JPEG bytes for testing."""
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), color=(255, 255, 255)).save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture
def sample_png_bytes() -> bytes:
    """Create minimal valid PNG bytes for testing."""
    # Minimal PNG: signature + IHDR + IDAT + IEND
    return bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
        0x00, 0x00, 0x00, 0x0D,  # IHDR length
        0x49, 0x48, 0x44, 0x52,  # IHDR chunk type
        0x00, 0x00, 0x00, 0x01,  # Width: 1
        0x00, 0x00, 0x00, 0x01,  # Height: 1
        0x08, 0x02,              # Bit depth: 8, Color type: 2 (RGB)
        0x00, 0x00, 0x00,        # Compression, filter, interlace
        0x90, 0x77, 0x53, 0xDE,  # CRC
        0x00, 0x00, 0x00, 0x0C,  # IDAT length
        0x49, 0x44, 0x41, 0x54,  # IDAT chunk type
        0x08, 0xD7, 0x63, 0xF8, 0xCF, 0xC0, 0x00, 0x00,
        0x00, 0x02, 0x00, 0x01,  # Compressed data
        0xE2, 0x21, 0xBC, 0x33,  # CRC
        0x00, 0x00, 0x00, 0x00,  # IEND length
        0x49, 0x45, 0x4E, 0x44,  # IEND chunk type
        0xAE, 0x42, 0x60, 0x82,  # CRC
    ])


__all__ = [
    "client",
    "test_data_dir",
    "repository",
    "sample_jpeg_bytes",
    "sample_png_bytes",
]
