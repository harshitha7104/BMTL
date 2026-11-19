"""
Tests for the ScrapTrust Copilot: engines, tools, providers and API.

No network calls are made: provider tests use fake SDK clients, and the API
tests use the offline provider with a synthetic waste-embedding index.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from app.api.routes.copilot import get_copilot_service
from app.core.config import settings
from app.copilot.engines.mineral import MineralEngine
from app.copilot.engines.waste import WasteSimilarityIndex, resolve_dataset_file
from app.copilot.providers.claude import ClaudeProvider
from app.copilot.providers.gemini import GeminiProvider
from app.copilot.providers.openai_chat import OpenAIChatProvider
from app.copilot.providers.registry import CopilotProviderRegistry, UnknownProviderError
from app.copilot.service import CopilotService
from app.copilot.tools import ToolContext, build_default_tools
from app.copilot.types import Attachment, ChatTurn
from app.main import app

CATEGORIES = ["metal waste", "plastic waste", "glass waste"]
DIM = 8


# --------------------------------------------------------------------------- fixtures
def _category_vector(i: int) -> np.ndarray:
    v = np.zeros(DIM, dtype=np.float32)
    v[i] = 1.0
    return v


@pytest.fixture
def fake_embeddings(tmp_path: Path) -> Path:
    """Tiny DINOv2-shaped index: 3 categories x 4 images, one K-Means cluster per category."""
    root = tmp_path / "embeddings"
    model_dir, cluster_dir = root / "dinov2_vits14", root / "clusters"
    model_dir.mkdir(parents=True)
    cluster_dir.mkdir(parents=True)
    rng = np.random.default_rng(0)
    vectors, paths, rows = [], [], []
    for ci, cat in enumerate(CATEGORIES):
        for j in range(4):
            v = _category_vector(ci) + rng.normal(0, 0.05, DIM).astype(np.float32)
            vectors.append(v / np.linalg.norm(v))
            idx = len(paths)
            path = f"data/raw/wastes/train/{cat}/{cat} ({j}).jpg"
            paths.append({"image_id": f"image_{idx:06d}", "embedding_index": idx, "file_path": path})
            rows.append({"image_id": f"image_{idx:06d}", "file_path": path, "embedding_index": idx, "cluster_id": ci})
    np.save(model_dir / "embeddings.npy", np.stack(vectors).astype(np.float32))
    np.save(model_dir / "status.npy", np.ones(len(vectors), dtype=np.int8))
    (model_dir / "image_paths.jsonl").write_text("\n".join(json.dumps(p) for p in paths), encoding="utf-8")
    (model_dir / "metadata.json").write_text(json.dumps({"model_name": "dinov2_vits14"}), encoding="utf-8")
    with open(cluster_dir / "cluster_assignments.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["image_id", "file_path", "embedding_index", "cluster_id"])
        writer.writeheader()
        writer.writerows(rows)
    (cluster_dir / "clustering_metrics.json").write_text(
        json.dumps({"method": "KMeans", "selected_k": 3, "selected_metrics": {"silhouette_score": 0.4}}), encoding="utf-8"
    )
    return root


def metal_embedder(_: bytes) -> np.ndarray:
    return _category_vector(0) + 0.02


@pytest.fixture
def waste_index(fake_embeddings: Path) -> WasteSimilarityIndex:
    return WasteSimilarityIndex(fake_embeddings, embedder=metal_embedder)


@pytest.fixture
def mineral_engine() -> MineralEngine:
    engine = MineralEngine(settings.mineral_path)
    if not engine.available:
        pytest.skip("mineral project not present")
    pytest.importorskip("scipy")
    pytest.importorskip("pandas")
    return engine


def _jpeg(size=(120, 120), color=(120, 120, 130)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def image_attachment(tmp_path: Path) -> Attachment:
    path = tmp_path / "image_1.jpg"
    path.write_bytes(_jpeg())
    return Attachment("image_1", "image", "scrap.jpg", "image/jpeg", str(path), path.stat().st_size)


# --------------------------------------------------------------------------- waste engine
def test_waste_index_query_votes_and_cluster(waste_index: WasteSimilarityIndex):
    result = waste_index.analyze_image(b"ignored", top_k=4)
    assert result["status"] == "ok"
    assert result["neighbour_category_votes"][0]["category"] == "metal waste"
    assert result["neighbour_agreement"] == "strong"
    assert result["nearest_cluster"]["cluster_id"] == 0
    assert all(n["source_category"] == "metal waste" for n in result["neighbours"])
    assert any("unverified" in c for c in result["caveats"])


def test_waste_index_flags_near_duplicate_and_overview(waste_index: WasteSimilarityIndex):
    waste_index.load()
    dup = waste_index.query(waste_index.vectors[5], top_k=3)
    assert dup["novelty"] == "near_duplicate_of_dataset_image"
    overview = waste_index.overview()
    assert overview["image_count"] == 12
    assert set(overview["source_categories"]) == set(CATEGORIES)
    assert waste_index.cluster_profile(1)["purity"] == 1.0
    with pytest.raises(KeyError):
        waste_index.cluster_profile(99)


def test_waste_index_reports_missing_torch(fake_embeddings: Path):
    def no_torch(_: bytes):
        raise ImportError("torch missing", name="torch")

    result = WasteSimilarityIndex(fake_embeddings, embedder=no_torch).analyze_image(b"x")
    assert result["status"] == "embedding_unavailable"
    assert "torch" in result["reason"]


def test_resolve_dataset_file_maps_to_existing_root(tmp_path: Path):
    target = tmp_path / "wastes" / "train" / "metal waste" / "a.jpg"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x")
    found = resolve_dataset_file("data/raw/wastes/train/metal waste/a.jpg", [tmp_path / "missing", tmp_path / "wastes"])
    assert found == target


# --------------------------------------------------------------------------- mineral engine
def test_mineral_engine_interprets_example_spectrum(mineral_engine: MineralEngine):
    data = (settings.mineral_path / "data" / "example_new_spectrum.csv").read_bytes()
    result = mineral_engine.interpret_file(data, "example.csv")
    assert result["status"] == "ok"
    first = result["results"][0]
    assert "Al-OH" in first["prediction"] or first["prediction_type"] in {"INFERRED", "OBSERVED"}
    assert 0.0 <= first["confidence"] <= 1.0
    json.dumps(result)  # must be JSON-serialisable for every provider


# --------------------------------------------------------------------------- tools
@pytest.mark.asyncio
async def test_tool_registry_errors_are_reported_not_raised(waste_index, mineral_engine, image_attachment):
    tools = build_default_tools(waste_index, mineral_engine)
    ctx = ToolContext({"image_1": image_attachment})
    bad = await tools.execute("analyze_waste_image", {"attachment_id": "image_9"}, ctx)
    assert bad.is_error and "Unknown attachment_id" in bad.output["error"]
    wrong_kind = await tools.execute("interpret_mineral_spectrum", {"attachment_id": "image_1"}, ctx)
    assert wrong_kind.is_error
    unknown = await tools.execute("nope", {}, ctx)
    assert unknown.is_error
    good = await tools.execute("assess_image_quality", {"attachment_id": "image_1"}, ctx)
    assert not good.is_error and "overall_score" in good.output


# --------------------------------------------------------------------------- providers (fake SDK clients)
class FakeAnthropic:
    def __init__(self, responses):
        self.calls = []
        self._responses = list(responses)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(json.loads(json.dumps(kwargs, default=lambda o: o.__dict__)))
        return self._responses.pop(0)


def _anthropic_msg(content, stop_reason):
    usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0)
    return SimpleNamespace(content=content, stop_reason=stop_reason, usage=usage, model="claude-opus-5-5")


@pytest.mark.asyncio
async def test_claude_provider_tool_loop(waste_index, mineral_engine, image_attachment):
    tool_use = SimpleNamespace(type="tool_use", id="toolu_1", name="analyze_waste_image", input={"attachment_id": "image_1"})
    final = SimpleNamespace(type="text", text="Looks like **metal waste** (moderate confidence).")
    fake = FakeAnthropic([_anthropic_msg([tool_use], "tool_use"), _anthropic_msg([final], "end_turn")])
    provider = ClaudeProvider(model="claude-opus-5-5", client=fake)

    result = await provider.respond(
        system="SYS", history=[ChatTurn("user", "hi"), ChatTurn("assistant", "hello")],
        user_turn=ChatTurn("user", "What is this?", ["image_1"]), images=[image_attachment],
        tools=build_default_tools(waste_index, mineral_engine), ctx=ToolContext({"image_1": image_attachment}), max_rounds=4,
    )

    assert "metal waste" in result.text
    assert [r.name for r in result.tool_calls] == ["analyze_waste_image"]
    first, second = fake.calls
    assert first["model"] == "claude-opus-5-5"
    assert first["fallbacks"] == "default" and first["betas"] == ["server-side-fallback-2026-07-01"]
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    current = first["messages"][-1]["content"]
    assert current[0]["type"] == "image" and current[0]["source"]["media_type"] == "image/jpeg"
    assert "image_1" in current[-1]["text"]
    tool_result = second["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "toolu_1"
    assert json.loads(tool_result["content"])["status"] == "ok"
    assert result.usage["input_tokens"] == 20


@pytest.mark.asyncio
async def test_claude_provider_handles_refusal(waste_index, mineral_engine):
    fake = FakeAnthropic([_anthropic_msg([], "refusal")])
    result = await ClaudeProvider(client=fake).respond(
        system="S", history=[], user_turn=ChatTurn("user", "x"), images=[],
        tools=build_default_tools(waste_index, mineral_engine), ctx=ToolContext(), max_rounds=2,
    )
    assert result.stop_reason == "refusal" and result.text


class FakeOpenAI:
    def __init__(self, responses):
        self.calls = []
        self._responses = list(responses)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(json.loads(json.dumps(kwargs, default=str)))
        return self._responses.pop(0)


def _openai_resp(message, finish):
    usage = SimpleNamespace(prompt_tokens=7, completion_tokens=3)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish)], usage=usage, model="gpt-4o")


class _Msg(SimpleNamespace):
    def model_dump(self, exclude_none=True):
        return {
            "role": "assistant",
            "content": self.content,
            "tool_calls": [
                {"id": t.id, "type": "function", "function": {"name": t.function.name, "arguments": t.function.arguments}}
                for t in self.tool_calls
            ],
        }


@pytest.mark.asyncio
async def test_openai_provider_tool_loop(waste_index, mineral_engine, image_attachment):
    call = SimpleNamespace(id="call_1", function=SimpleNamespace(name="get_waste_dataset_overview", arguments="{}"))
    fake = FakeOpenAI(
        [
            _openai_resp(_Msg(content=None, tool_calls=[call], refusal=None), "tool_calls"),
            _openai_resp(SimpleNamespace(content="12 images in 3 categories.", tool_calls=None, refusal=None), "stop"),
        ]
    )
    provider = OpenAIChatProvider(api_key="k", model="gpt-4o", client=fake)
    result = await provider.respond(
        system="SYS", history=[], user_turn=ChatTurn("user", "overview?", ["image_1"]), images=[image_attachment],
        tools=build_default_tools(waste_index, mineral_engine), ctx=ToolContext({"image_1": image_attachment}), max_rounds=4,
    )
    assert result.text.startswith("12 images")
    first, second = fake.calls
    assert first["messages"][0] == {"role": "system", "content": "SYS"}
    assert first["messages"][-1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert first["tools"][0]["type"] == "function"
    tool_msg = second["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "call_1"
    assert json.loads(tool_msg["content"])["image_count"] == 12


class FakeGemini:
    def __init__(self, responses):
        self.calls = []
        self._responses = list(responses)
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._gen))

    async def _gen(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_gemini_provider_tool_loop(waste_index, mineral_engine):
    pytest.importorskip("google.genai")
    from google.genai import types

    call = types.FunctionCall(name="get_waste_cluster_profile", args={"cluster_id": 2})
    first = SimpleNamespace(
        function_calls=[call], text=None, usage_metadata=None,
        candidates=[SimpleNamespace(finish_reason=None, content=types.Content(role="model", parts=[types.Part(function_call=call)]))],
    )
    second = SimpleNamespace(function_calls=None, text="Cluster 2 is all glass.", usage_metadata=None,
                             candidates=[SimpleNamespace(finish_reason="STOP", content=None)])
    fake = FakeGemini([first, second])
    result = await GeminiProvider(api_key="k", client=fake).respond(
        system="SYS", history=[ChatTurn("assistant", "hi")], user_turn=ChatTurn("user", "cluster 2?"), images=[],
        tools=build_default_tools(waste_index, mineral_engine), ctx=ToolContext(), max_rounds=4,
    )
    assert result.text == "Cluster 2 is all glass."
    assert result.tool_calls[0].output["source_category_composition"][0]["category"] == "glass waste"
    sent = fake.calls[1]["contents"][-1].parts[0].function_response
    assert sent.name == "get_waste_cluster_profile" and "result" in sent.response
    assert fake.calls[0]["contents"][0].role == "model"


def test_registry_auto_falls_back_to_offline():
    registry = CopilotProviderRegistry([ClaudeProvider(api_key=""), OpenAIChatProvider(api_key="", model="gpt-4o")])
    registry._providers["claude"].is_configured = lambda: False  # ignore any ANTHROPIC_API_KEY in the env
    assert registry.default_name() == "offline"
    with pytest.raises(UnknownProviderError):
        registry.resolve("openai")
    with pytest.raises(UnknownProviderError):
        registry.resolve("does-not-exist")


# --------------------------------------------------------------------------- API (offline provider)
class FakeTranscriber:
    """Stands in for Whisper: returns the transcript registered for a filename."""

    def __init__(self):
        self.scripts = {}
        self.calls = []

    def transcribe(self, data: bytes, filename: str) -> dict:
        self.calls.append(filename)
        return {"text": self.scripts.get(filename, ""), "language": "en", "duration_s": 2.0}


@pytest.fixture
def transcriber() -> FakeTranscriber:
    return FakeTranscriber()


class FakeMaterialIdentifier:
    """Stands in for CLIP (no 600 MB download in tests) but runs the real colour analysis:
    mostly copper-coloured items are reported as copper, everything else as steel."""

    def identify(self, image_bytes: bytes, top_k: int = 5) -> dict:
        from app.copilot.engines.material import CAVEATS, MATERIALS, colour_profile

        colour = colour_profile(image_bytes)
        key = "copper" if colour["copper_coloured"] > 0.5 else "steel"
        mat = next(m for m in MATERIALS if m.key == key)
        other = next(m for m in MATERIALS if m.key == ("steel" if key == "copper" else "aluminium"))
        return {
            "status": "ok", "most_likely": mat.name, "key": mat.key, "confidence": "high", "probability": 0.9,
            "top_matches": [
                {"material": mat.name, "key": mat.key, "family": mat.family, "probability": 0.9, "dataset_category": mat.dataset_category},
                {"material": other.name, "key": other.key, "family": other.family, "probability": 0.05, "dataset_category": other.dataset_category},
            ],
            "family_probabilities": {}, "colour": colour, "guidance": mat.guidance, "knowledge_topic": mat.kb_query,
            "is_scrap": True, "model": "fake-clip", "caveats": CAVEATS,
        }


@pytest.fixture
def offline_service(tmp_path, waste_index, mineral_engine, transcriber):
    registry = CopilotProviderRegistry([], default="offline")
    service = CopilotService(
        storage_dir=tmp_path / "copilot",
        providers=registry,
        tools=build_default_tools(waste_index, mineral_engine, None, FakeMaterialIdentifier()),
        max_upload_bytes=5 * 1024 * 1024,
        max_images_per_turn=3,
        allowed_image_types=["image/jpeg", "image/png", "image/webp"],
        waste_index=waste_index,
        transcriber=transcriber,
    )
    app.dependency_overrides[get_copilot_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_copilot_service, None)


@pytest.mark.asyncio
async def test_api_chat_image_spectrum_and_followup(client, offline_service):
    providers = (await client.get("/api/v1/copilot/providers")).json()
    assert providers["default"] == "offline"

    resp = await client.post(
        "/api/v1/copilot/chat",
        data={"message": "What scrap is this?"},
        files=[("files", ("yard.jpg", _jpeg(), "image/jpeg"))],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "offline"
    assert {c["name"] for c in body["tool_calls"]} == {"identify_material", "analyze_waste_image", "assess_image_quality", "assess_black_mass_xrf"}  # photos are also checked for XRF screen readings
    assert "metal waste" in body["reply"]
    assert body["attachments"][0]["attachment_id"] == "image_1" and body["attachments"][0]["path"] is None
    session_id = body["session_id"]

    spectrum = (settings.mineral_path / "data" / "example_new_spectrum.csv").read_bytes()
    resp2 = await client.post(
        "/api/v1/copilot/chat",
        data={"session_id": session_id},
        files=[("files", ("rock.csv", spectrum, "text/csv"))],
    )
    assert resp2.status_code == 200, resp2.text
    body2 = resp2.json()
    assert body2["tool_calls"][0]["name"] == "interpret_mineral_spectrum"
    assert "spectral interpretation" in body2["reply"]
    assert body2["attachments"][0]["attachment_id"] == "spectrum_1"

    session = (await client.get(f"/api/v1/copilot/sessions/{session_id}")).json()
    assert len(session["turns"]) == 4
    assert set(session["attachments"]) == {"image_1", "spectrum_1"}
    assert all(a["path"] is None for a in session["attachments"].values())


@pytest.mark.asyncio
async def test_api_chat_text_only_overview(client, offline_service):
    resp = await client.post("/api/v1/copilot/chat", data={"message": "Give me a dataset overview"})
    assert resp.status_code == 200
    assert "12 images" in resp.json()["reply"]


@pytest.mark.asyncio
async def test_api_chat_rejects_bad_input(client, offline_service):
    empty = await client.post("/api/v1/copilot/chat", data={"message": ""})
    assert empty.status_code == 400
    bad_type = await client.post(
        "/api/v1/copilot/chat", data={"message": "x"}, files=[("files", ("a.exe", b"MZ", "application/octet-stream"))]
    )
    assert bad_type.status_code == 400
    traversal = await client.post("/api/v1/copilot/chat", data={"message": "x", "session_id": "../../etc"})
    assert traversal.status_code == 400
    missing = await client.get("/api/v1/copilot/sessions/0123456789abcdef")
    assert missing.status_code == 404
    unknown_provider = await client.post("/api/v1/copilot/chat", data={"message": "x", "provider": "skynet"})
    assert unknown_provider.status_code == 400


# --------------------------------------------------------------------------- feedback / reviewed labels
@pytest.mark.asyncio
async def test_api_feedback_records_reviewed_labels(client, offline_service):
    providers = (await client.get("/api/v1/copilot/providers")).json()
    assert providers["waste_categories"] == sorted(CATEGORIES)

    chat = (
        await client.post(
            "/api/v1/copilot/chat",
            data={"message": "What is this?"},
            files=[("files", ("a.jpg", _jpeg(), "image/jpeg")), ("files", ("b.jpg", _jpeg(color=(10, 90, 10)), "image/jpeg"))],
        )
    ).json()
    sid = chat["session_id"]

    # Reviewer says the model was wrong: it's glass, not metal.
    res = await client.post(
        f"/api/v1/copilot/sessions/{sid}/feedback",
        json={"turn_index": 1, "rating": "down", "corrected_category": "glass waste", "note": "green bottle shards"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["labels_recorded"] == 2 and body["predicted_category"] == "metal waste"

    session = (await client.get(f"/api/v1/copilot/sessions/{sid}")).json()
    assert session["turns"][1]["feedback"]["corrected_category"] == "glass waste"

    export = (await client.get("/api/v1/copilot/feedback/export")).json()
    assert export["count"] == 2
    row = export["labels"][0]
    assert row["verified_category"] == "glass waste" and row["model_predicted_category"] == "metal waste"
    assert len(row["sha256"]) == 64

    # A thumbs-up on a later image answer confirms the model's own prediction.
    chat2 = (
        await client.post("/api/v1/copilot/chat", data={"session_id": sid}, files=[("files", ("c.jpg", _jpeg(), "image/jpeg"))])
    ).json()
    assert chat2["attachments"][0]["attachment_id"] == "image_3"
    up = await client.post(f"/api/v1/copilot/sessions/{sid}/feedback", json={"turn_index": 3, "rating": "up"})
    assert up.json()["labels_recorded"] == 1

    summary = (await client.get("/api/v1/copilot/feedback/summary")).json()
    assert summary["reviewed_images"] == 3 and summary["thumbs_up"] == 1 and summary["thumbs_down"] == 2
    assert summary["verified_labels_per_category"] == {"glass waste": 2, "metal waste": 1}
    assert summary["model_agreement_with_reviewers"] == round(1 / 3, 3)


@pytest.mark.asyncio
async def test_api_feedback_rejects_bad_targets(client, offline_service):
    sid = (await client.post("/api/v1/copilot/chat", data={"message": "dataset overview"})).json()["session_id"]
    user_turn = await client.post(f"/api/v1/copilot/sessions/{sid}/feedback", json={"turn_index": 0, "rating": "up"})
    assert user_turn.status_code == 400
    out_of_range = await client.post(f"/api/v1/copilot/sessions/{sid}/feedback", json={"turn_index": 9, "rating": "up"})
    assert out_of_range.status_code == 400
    bad_rating = await client.post(f"/api/v1/copilot/sessions/{sid}/feedback", json={"turn_index": 1, "rating": "meh"})
    assert bad_rating.status_code == 422
    text_only = await client.post(f"/api/v1/copilot/sessions/{sid}/feedback", json={"turn_index": 1, "rating": "down"})
    assert text_only.status_code == 200 and text_only.json()["labels_recorded"] == 0


# --------------------------------------------------------------------------- scope, knowledge, voice, video, documents
def _tiny_video_with_audio() -> bytes:
    """2-second MP4: four solid-colour frames plus a short tone soundtrack."""
    av = pytest.importorskip("av")
    buf = io.BytesIO()
    with av.open(buf, "w", format="mp4") as c:
        vs = c.add_stream("mpeg4", rate=2)
        vs.width, vs.height, vs.pix_fmt = 160, 120, "yuv420p"
        aus = c.add_stream("aac", rate=16000)
        aus.layout = "mono"
        for i in range(4):
            frame = av.VideoFrame.from_image(Image.new("RGB", (160, 120), (60 * i, 100, 140)))
            for p in vs.encode(frame):
                c.mux(p)
        for p in vs.encode():
            c.mux(p)
        tone = (np.sin(np.linspace(0, 440 * 2 * np.pi * 2, 32000)) * 8000).astype(np.int16)
        for start in range(0, tone.size, 1024):
            fr = av.AudioFrame.from_ndarray(tone[start:start + 1024].reshape(1, -1), format="s16", layout="mono")
            fr.sample_rate = 16000
            for p in aus.encode(fr):
                c.mux(p)
        for p in aus.encode():
            c.mux(p)
    return buf.getvalue()


WEBM_MAGIC = bytes([0x1A, 0x45, 0xDF, 0xA3])


@pytest.mark.asyncio
async def test_off_topic_questions_are_declined(client, offline_service):
    for question in ["What is the capital of France?", "Write a python function to reverse a string", "Who will lead the team next season?"]:
        body = (await client.post("/api/v1/copilot/chat", data={"message": question})).json()
        assert "couldn't match that" in body["reply"], question
        assert body["tool_calls"] == [] and body["stop_reason"] == "off_topic"


@pytest.mark.asyncio
async def test_small_talk_and_domain_questions(client, offline_service):
    hello = (await client.post("/api/v1/copilot/chat", data={"message": "hello"})).json()
    assert "ACE Green's assistant" in hello["reply"]

    lithium = (await client.post("/api/v1/copilot/chat", data={"message": "How do I store swollen lithium batteries?"})).json()
    assert lithium["tool_calls"][0]["name"] == "search_knowledge_base"
    assert "Lithium-ion battery safety" in lithium["reply"] and "thermal runaway" in lithium["reply"]

    minerals = (await client.post("/api/v1/copilot/chat", data={"message": "How do I tell kaolinite from muscovite?"})).json()
    assert "2165" in minerals["reply"]

    project = (await client.post("/api/v1/copilot/chat", data={"message": "How many images are in your dataset?"})).json()
    assert "couldn't match that" not in project["reply"]


@pytest.mark.asyncio
async def test_voice_message_is_transcribed_and_answered(client, offline_service, transcriber):
    transcriber.scripts = {"voice.webm": "How should I handle a broken fluorescent tube?", "joke.webm": "Tell me a joke"}
    body = (
        await client.post("/api/v1/copilot/chat", files=[("files", ("voice.webm", WEBM_MAGIC + b"fake", "audio/webm"))])
    ).json()
    att = body["attachments"][0]
    assert att["kind"] == "audio" and att["text"] == "How should I handle a broken fluorescent tube?"
    assert "Fluorescent lamps" in body["reply"] and "broken fluorescent tube" in body["reply"]

    off = (await client.post("/api/v1/copilot/chat", files=[("files", ("joke.webm", WEBM_MAGIC + b"x", "audio/webm"))])).json()
    assert "Tell me a joke" in off["reply"] and "couldn't match that" in off["reply"]


@pytest.mark.asyncio
async def test_video_frames_analysed_and_soundtrack_transcribed(client, offline_service, transcriber):
    transcriber.scripts = {"walk.mp4": "Mostly aluminium extrusions here"}
    body = (
        await client.post(
            "/api/v1/copilot/chat",
            data={"message": "What is in this video?"},
            files=[("files", ("walk.mp4", _tiny_video_with_audio(), "video/mp4"))],
        )
    ).json()
    kinds = [(a["attachment_id"], a["kind"], a["source"]) for a in body["attachments"]]
    assert kinds[0] == ("video_1", "video", None)
    frames = [k for k in kinds if k[1] == "image"]
    assert len(frames) == 4 and all(src == "video_1" for _, _, src in frames)
    assert body["attachments"][0]["text"] == "Mostly aluminium extrusions here"
    assert sum(c["name"] == "analyze_waste_image" for c in body["tool_calls"]) == 4
    assert "frame from video_1" in body["reply"] and "Mostly aluminium extrusions here" in body["reply"]


@pytest.mark.asyncio
async def test_documents_and_csv_routing(client, offline_service):
    notes = b"Yard intake log\nLoad 14: mixed copper wire with PVC insulation, about 40% recovery expected.\n" * 3
    doc = (
        await client.post(
            "/api/v1/copilot/chat", data={"message": "Summarise this log"}, files=[("files", ("intake.txt", notes, "text/plain"))]
        )
    ).json()
    assert doc["attachments"][0]["kind"] == "document" and "copper wire" in doc["attachments"][0]["text"]
    assert "document `intake.txt`" in doc["reply"]

    table = b"load,weight_kg\n" + b"".join(f"{i},{100 + i}\n".encode() for i in range(30))
    sheet = (await client.post("/api/v1/copilot/chat", files=[("files", ("loads.csv", table, "text/csv"))])).json()
    assert sheet["attachments"][0]["kind"] == "document"

    spectrum = (settings.mineral_path / "data" / "example_new_spectrum.csv").read_bytes()
    spec = (await client.post("/api/v1/copilot/chat", files=[("files", ("s.csv", spectrum, "text/csv"))])).json()
    assert spec["attachments"][0]["kind"] == "spectrum"


def test_llm_sees_transcripts_and_document_text(tmp_path):
    from app.copilot.providers.base import render_turn_text

    audio = Attachment("audio_1", "audio", "q.webm", "audio/webm", str(tmp_path / "q"), 10, text="Is this brass or bronze?")
    doc = Attachment("document_1", "document", "spec.pdf", "application/pdf", str(tmp_path / "d"), 10, text="Alloy C26000")
    text = render_turn_text(ChatTurn("user", "Please help", ["audio_1", "document_1"]), {"audio_1": audio, "document_1": doc})
    assert "[Transcript of audio_1 (q.webm)]\nIs this brass or bronze?" in text
    assert "[Contents of document_1 (spec.pdf)]\nAlloy C26000" in text


@pytest.mark.asyncio
async def test_sessions_list_attachment_preview_delete_and_dictation(client, offline_service, transcriber):
    first = (await client.post("/api/v1/copilot/chat", data={"message": "What is black mass?"})).json()
    second = (
        await client.post("/api/v1/copilot/chat", data={"message": "Check this"}, files=[("files", ("p.jpg", _jpeg(), "image/jpeg"))])
    ).json()

    listing = (await client.get("/api/v1/copilot/sessions")).json()["sessions"]
    assert [s["session_id"] for s in listing] == [second["session_id"], first["session_id"]]
    assert listing[1]["title"] == "What is black mass?"

    img = await client.get(f"/api/v1/copilot/sessions/{second['session_id']}/attachments/image_1")
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg" and img.content[:2] == b"\xff\xd8"
    missing = await client.get(f"/api/v1/copilot/sessions/{second['session_id']}/attachments/image_9")
    assert missing.status_code == 404

    assert (await client.delete(f"/api/v1/copilot/sessions/{first['session_id']}")).status_code == 200
    assert (await client.get(f"/api/v1/copilot/sessions/{first['session_id']}")).status_code == 404
    assert len((await client.get("/api/v1/copilot/sessions")).json()["sessions"]) == 1

    transcriber.scripts = {"dictation.webm": "Is copper wire with insulation worth stripping?"}
    dictated = await client.post("/api/v1/copilot/transcribe", files={"file": ("dictation.webm", WEBM_MAGIC, "audio/webm")})
    assert dictated.status_code == 200 and dictated.json()["text"].startswith("Is copper wire")


# --------------------------------------------------------------------------- material identification
def _copper_offcuts_jpeg() -> bytes:
    """Reddish-orange metal pieces on a light background, like a copper offcut photo."""
    from PIL import ImageDraw

    im = Image.new("RGB", (400, 300), (236, 236, 238))
    d = ImageDraw.Draw(im)
    for i, colour in enumerate([(184, 98, 52), (160, 82, 45), (199, 116, 70), (150, 76, 40)]):
        d.polygon([(30 + 90 * i, 40), (100 + 90 * i, 60), (90 + 90 * i, 250), (25 + 90 * i, 230)], fill=colour)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def test_colour_profile_detects_copper_and_ignores_background():
    from app.copilot.engines.material import colour_profile

    copper = colour_profile(_copper_offcuts_jpeg())
    assert copper["dominant"] == "copper_coloured" and copper["copper_coloured"] > 0.8
    assert 0.2 < copper["item_pixel_share"] < 0.9  # light background excluded

    grey = colour_profile(_jpeg(size=(200, 200), color=(128, 128, 132)))
    assert grey["copper_coloured"] < 0.05


def test_material_catalogue_is_consistent():
    from app.copilot.engines.material import MATERIALS

    keys = [m.key for m in MATERIALS]
    assert len(keys) == len(set(keys))
    assert {"copper", "brass", "aluminium", "steel", "stainless", "li_battery", "not_scrap"} <= set(keys)
    assert all(len(m.prompts) >= 2 and m.guidance for m in MATERIALS)


@pytest.mark.asyncio
async def test_copper_photo_is_named_copper(client, offline_service):
    body = (
        await client.post(
            "/api/v1/copilot/chat",
            data={"message": "What metal is this?"},
            files=[("files", ("offcuts.jpg", _copper_offcuts_jpeg(), "image/jpeg"))],
        )
    ).json()
    material = next(c for c in body["tool_calls"] if c["name"] == "identify_material")
    assert material["output"]["most_likely"] == "Copper"
    assert "### image_1: Copper" in body["reply"] and "**Identification:** Copper" in body["reply"]
    assert "copper-coloured" in body["reply"] and "Non-magnetic" in body["reply"]


@pytest.mark.asyncio
async def test_material_tool_unavailable_is_graceful(waste_index, mineral_engine, image_attachment):
    tools = build_default_tools(waste_index, mineral_engine)  # no identifier configured
    rec = await tools.execute("identify_material", {"attachment_id": "image_1"}, ToolContext({"image_1": image_attachment}))
    assert not rec.is_error and rec.output["status"] == "unavailable"
