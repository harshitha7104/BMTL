"""
Copilot tools: provider-neutral definitions (JSON Schema) + async handlers.

Each provider adapter converts ``ToolSpec`` into its own wire format
(Anthropic tools, OpenAI functions, Gemini function declarations) and calls
``ToolRegistry.execute`` when the model requests a tool.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from app.copilot.engines.black_mass import BlackMassEngine, BlackMassEngineUnavailable
from app.copilot.engines.knowledge import KnowledgeBase
from app.copilot.engines.mineral import MineralEngine, MineralEngineUnavailable
from app.copilot.engines.waste import WasteSimilarityIndex
from app.copilot.types import Attachment, ToolCallRecord

log = logging.getLogger(__name__)

MAX_TOOL_OUTPUT_CHARS = 12000


@dataclass
class ToolContext:
    """Per-request state the tools may read: the session's attachments, the black-mass results of this
    conversation (earlier turns + this turn, for the lot-analyst and report-writer agents), the signed-in
    user, and a callback to save a generated file into the conversation."""

    attachments: Dict[str, Attachment] = field(default_factory=dict)
    results: List[Dict[str, Any]] = field(default_factory=list)
    user: Optional[str] = None
    save_file: Optional[Callable[[str, str, bytes], Dict[str, Any]]] = None

    def get(self, attachment_id: str, kind: Optional[str] = None) -> Attachment:
        att = self.attachments.get(attachment_id)
        if att is None:
            known = ", ".join(self.attachments) or "none"
            raise ToolInputError(f"Unknown attachment_id '{attachment_id}'. Available: {known}")
        if kind and att.kind != kind:
            raise ToolInputError(f"Attachment '{attachment_id}' is a {att.kind}, expected a {kind}")
        return att


_PATHS = re.compile(r"(?:\b[A-Za-z]:[\\/]|\\\\|/(?:srv|opt|home|usr|tmp|data|var|root|mnt)/)[^\s'\"]*")


def _scrub(message: str) -> str:
    """Remove server file paths from a message shown to users (security audit N-04)."""
    return _PATHS.sub("[server path]", message)


class ToolInputError(ValueError):
    """Bad tool arguments; reported back to the model as an error result."""


Handler = Callable[[Dict[str, Any], ToolContext], Awaitable[Any]]


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Handler


class ToolRegistry:
    def __init__(self, specs: List[ToolSpec]) -> None:
        self._specs = {s.name: s for s in specs}

    @property
    def specs(self) -> List[ToolSpec]:
        return list(self._specs.values())  # insertion order is stable (prompt-cache friendly)

    async def execute(self, name: str, arguments: Dict[str, Any], ctx: ToolContext) -> ToolCallRecord:
        start = time.perf_counter()
        spec = self._specs.get(name)
        if spec is None:
            output: Any = {"error": f"Unknown tool '{name}'"}
            is_error = True
        else:
            try:
                output = await spec.handler(arguments or {}, ctx)
                is_error = False
                if name == "assess_black_mass_xrf":   # feed the lot-analyst / report-writer agents
                    ctx.results.append({"name": name, "input": arguments or {}, "output": output, "is_error": False})
            except (ToolInputError, KeyError, ValueError) as exc:     # problems with the user's input: explain them
                output, is_error = {"error": _scrub(str(exc))}, True
            except (MineralEngineUnavailable, BlackMassEngineUnavailable, FileNotFoundError, OSError) as exc:
                # Security audit N-04: these carry server paths and model file names; log them, tell the user plainly
                ref = uuid.uuid4().hex[:8]
                log.warning("Tool %s unavailable [%s]: %s", name, ref, exc)
                output, is_error = {"error": f"This analysis is not available on the server right now (reference {ref})."}, True
            except Exception:  # never let a tool crash the chat turn, and never show internals
                ref = uuid.uuid4().hex[:8]
                log.exception("Tool %s failed [%s]", name, ref)
                output, is_error = {"error": f"This analysis failed unexpectedly (reference {ref})."}, True
        return ToolCallRecord(
            name=name,
            input=arguments or {},
            output=output,
            is_error=is_error,
            duration_ms=int((time.perf_counter() - start) * 1000),
        )


def serialize_tool_output(output: Any) -> str:
    """JSON text sent back to the model, capped so one tool can't flood the context."""
    text = json.dumps(output, ensure_ascii=False, default=str)
    if len(text) > MAX_TOOL_OUTPUT_CHARS:
        text = text[:MAX_TOOL_OUTPUT_CHARS] + '... [truncated]"'
    return text


def _schema(properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


ATTACHMENT_PROP = {"type": "string", "description": "Attachment id from the conversation, e.g. 'image_1' or 'spectrum_1'."}


def build_default_tools(
    waste_index: WasteSimilarityIndex,
    mineral_engine: MineralEngine,
    knowledge_base: Optional[KnowledgeBase] = None,
    material_identifier=None,
    black_mass_engine: Optional[BlackMassEngine] = None,
) -> ToolRegistry:
    from app.core.config import settings
    from app.services.image_quality_service import ImageQualityService
    from app.utils.image_utils import create_image_data

    quality_service = ImageQualityService()
    kb = knowledge_base or KnowledgeBase()
    black_mass = black_mass_engine or BlackMassEngine()

    async def search_knowledge_base(args: Dict[str, Any], ctx: ToolContext) -> Any:
        query = str(args.get("query", "")).strip()
        if not query:
            raise ToolInputError("query is required")
        hits = await asyncio.to_thread(kb.search, query, int(args.get("k", 3)))
        return {"query": query, "results": hits, "note": "Curated ScrapTrust reference notes; cite them as general guidance."}

    async def list_identifiable_materials(args: Dict[str, Any], ctx: ToolContext) -> Any:
        from app.copilot.engines.material_catalog import catalogue_by_group

        groups = catalogue_by_group()
        return {"total": sum(len(v) for v in groups.values()), "by_group": groups}

    async def identify_material(args: Dict[str, Any], ctx: ToolContext) -> Any:
        att = ctx.get(str(args.get("attachment_id", "")), "image")
        if material_identifier is None:
            return {"status": "unavailable", "reason": "material identifier not configured"}
        return await asyncio.to_thread(material_identifier.identify, att.read_bytes(), int(args.get("top_k", 5)))

    async def analyze_waste_image(args: Dict[str, Any], ctx: ToolContext) -> Any:
        att = ctx.get(str(args.get("attachment_id", "")), "image")
        top_k = int(args.get("top_k", 8))
        data = att.read_bytes()
        return await asyncio.to_thread(waste_index.analyze_image, data, top_k)

    async def assess_image_quality(args: Dict[str, Any], ctx: ToolContext) -> Any:
        att = ctx.get(str(args.get("attachment_id", "")), "image")
        image = create_image_data(att.read_bytes(), att.filename, att.content_type, settings.allowed_image_types_list)
        quality = await asyncio.to_thread(quality_service.assess_quality, [image])
        result = quality.model_dump(mode="json")
        result["image"] = {"width": image.width, "height": image.height, "format": image.format}
        return result

    async def get_waste_cluster_profile(args: Dict[str, Any], ctx: ToolContext) -> Any:
        return await asyncio.to_thread(waste_index.cluster_profile, int(args["cluster_id"]))

    async def get_waste_dataset_overview(args: Dict[str, Any], ctx: ToolContext) -> Any:
        return await asyncio.to_thread(waste_index.overview)

    async def interpret_mineral_spectrum(args: Dict[str, Any], ctx: ToolContext) -> Any:
        att = ctx.get(str(args.get("attachment_id", "")), "spectrum")
        return await asyncio.to_thread(mineral_engine.interpret_file, att.read_bytes(), att.filename)

    async def get_mineral_model_info(args: Dict[str, Any], ctx: ToolContext) -> Any:
        return await asyncio.to_thread(mineral_engine.model_card)

    async def assess_black_mass_xrf(args: Dict[str, Any], ctx: ToolContext) -> Any:
        attachment_id = args.get("attachment_id")
        if attachment_id:
            att = ctx.get(str(attachment_id))
            if att.kind == "xrf" and att.filename.lower().endswith(".pdz"):
                return await asyncio.to_thread(black_mass.assess_pdz, att.path)
            if att.kind in ("xrf", "spectrum"):
                readings = await asyncio.to_thread(black_mass.table_readings, att.read_bytes(), att.filename)
                if readings:
                    return await asyncio.to_thread(black_mass.assess_readings, readings, att.attachment_id)
                return {"source": att.attachment_id, "readings_found": 0, "status": "no element columns found in this table"}
            if att.kind == "image":
                return await asyncio.to_thread(black_mass.assess_image, att.read_bytes(), att.attachment_id)
            if att.kind in ("document", "audio", "video"):
                return await asyncio.to_thread(black_mass.assess_text, att.text or "", att.attachment_id)
            raise ToolInputError(f"cannot read element values from a {att.kind} attachment")
        if args.get("text"):
            return await asyncio.to_thread(black_mass.assess_text, str(args["text"])[:20000], "message text")
        values = args.get("values") or {}
        if not values:
            raise ToolInputError("give attachment_id, text, or values (element -> wt%)")
        basis = str(args.get("basis", "type_standardised"))
        return await asyncio.to_thread(black_mass.assess_values, values, basis, str(args.get("instrument", "S1 TITAN")))

    async def get_black_mass_model_info(args: Dict[str, Any], ctx: ToolContext) -> Any:
        return await asyncio.to_thread(black_mass.model_card)

    async def analyse_lot(args: Dict[str, Any], ctx: ToolContext) -> Any:
        from app.copilot.agents.lot import analyse
        from app.copilot.agents.readings import collect

        return analyse(collect(ctx.results))

    async def write_assessment_report(args: Dict[str, Any], ctx: ToolContext) -> Any:
        from app.copilot.agents.readings import collect
        from app.copilot.agents.report import build_docx

        readings = collect(ctx.results)
        if not readings:
            raise ToolInputError("no black-mass readings in this conversation yet; assess some data first")
        if ctx.save_file is None:
            raise ToolInputError("reports cannot be saved in this context")
        title = str(args.get("title") or "Black mass assessment")[:120]
        summary = str(args.get("summary") or "")[:3000] or None
        data = await asyncio.to_thread(build_docx, readings, title=title, author=ctx.user or "", ai_summary=summary)
        safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in title).strip().replace(" ", "_")[:60] or "report"
        saved = ctx.save_file(f"{safe}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", data)
        return {"status": "ok", "report": saved, "readings_in_report": len(readings),
                "note": "Word report saved to this conversation; the user can download it from the answer."}

    return ToolRegistry(
        [
            ToolSpec(
                "assess_black_mass_xrf",
                "Assess lithium-ion battery black mass using BMTL's models trained on ACE's real ICP-referenced samples. "
                "Works on ANY input that contains element values: a Bruker .pdz file, a CSV/XLSX/JSON table (any column "
                "names, XRF or ICP), a PDF/text report or voice-note transcript (attachment_id of the document/audio), a "
                "PHOTO of an XRF screen or printout (attachment_id of the image; read by local OCR), free text with values "
                "(text), or element values typed as numbers (values). Returns per element the OBSERVED gun value and an INFERRED ICP-equivalent "
                "value with a 90 % band, an INFERRED lithium estimate (LiX, from the metals; XRF cannot measure Li), and "
                "a material call (NMC, LCO, LFP, lead-acid paste, instrument-mode artefact, or UNKNOWN) with confidence.",
                _schema(
                    {
                        "attachment_id": {"type": "string", "description": "Any attachment id: xrf_N, document_N, image_N, audio_N, spectrum_N."},
                        "text": {"type": "string", "description": "Free text containing element values, e.g. 'Ni 18.1%, Co 7.9, Mn 9.2'."},
                        "values": {"type": "object", "description": "Element -> wt% (number) or '<LOD', e.g. {\"Ni\": 18.1, \"Co\": 7.9}.",
                                   "additionalProperties": {"type": ["number", "string"]}},
                        "basis": {"type": "string", "enum": ["type_standardised", "factory"],
                                  "description": "Calibration the values come from (default type_standardised = Bruker 'Black mass powder')."},
                        "instrument": {"type": "string", "description": "'S1 TITAN' (default) or 'xSORT'."},
                    },
                    [],
                ),
                assess_black_mass_xrf,
            ),
            ToolSpec(
                "analyse_lot",
                "Lot-analyst agent: compare ALL black-mass readings assessed in this conversation (every file, row, photo or "
                "typed reading). Returns per-element mean, range and spread, robust outliers, whether the chemistry is "
                "consistent, and which samples to send for ICP-OES first and why. Use when several readings exist, or the user "
                "asks to compare, find odd bags, or plan lab testing.",
                _schema({}, []),
                analyse_lot,
            ),
            ToolSpec(
                "write_assessment_report",
                "Report-writer agent: create a downloadable Word (.docx) assessment report of all black-mass readings in this "
                "conversation (values read, ICP-equivalent estimates with 90 % ranges, lithium, material, compound, lot analysis, "
                "ICP recommendations, method and limits). Optionally pass a short plain-language summary you wrote from the tool "
                "results; never put numbers in the summary that are not in the tool results. Use when the user asks for a report, "
                "a document, a summary file or something to share.",
                _schema({"title": {"type": "string", "description": "Report title, e.g. 'Lot B-19217 assessment'."},
                         "summary": {"type": "string", "description": "3-6 sentence plain-language summary based only on tool results."}}, []),
                write_assessment_report,
            ),
            ToolSpec(
                "get_black_mass_model_info",
                "Describe the black-mass models: training data (9 ICP-referenced ACE samples), per-element accuracy, "
                "lithium method, material detector and limitations.",
                _schema({}, []),
                get_black_mass_model_info,
            ),
            ToolSpec(
                "identify_material",
                "Name what is in an attached photo: metals (copper, brass, bronze, aluminium, steel, iron, cast iron, "
                "stainless, galvanised, lead, zinc, titanium...), plastics by type (PET, HDPE, PVC, film, PP, polystyrene), "
                "glass by colour, paper, e-waste, battery types, lamps, automotive parts, construction materials, and "
                "minerals and rocks (quartz, feldspar, mica, calcite, pyrite, chalcopyrite, galena, malachite, hematite, "
                "magnetite, granite, basalt, marble...). Uses zero-shot CLIP matching; returns a plain headline, the "
                "group and specific material with probabilities and confidence, a rough composition by area for mixed "
                "loads, a colour analysis and handling guidance. Use it for every photo.",
                _schema(
                    {
                        "attachment_id": ATTACHMENT_PROP,
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 10, "description": "Alternatives to return (default 5)."},
                    },
                    ["attachment_id"],
                ),
                identify_material,
            ),
            ToolSpec(
                "list_identifiable_materials",
                "List every material, mineral and rock ScrapTrust can name in photos, grouped (Metal, Mineral, Rock, "
                "Plastic, Glass, ...). Use when the user asks what you can identify or detect.",
                _schema({}, []),
                list_identifiable_materials,
            ),
            ToolSpec(
                "analyze_waste_image",
                "Embed an attached waste/scrap photo with the project's DINOv2 model and compare it against the "
                "11,521-image waste dataset. Returns nearest dataset images with similarity, the (unverified) folder "
                "categories of those neighbours as weighted votes, the nearest unsupervised K-Means cluster with its "
                "category composition, and a novelty flag. Use for any question about what an attached photo shows.",
                _schema(
                    {
                        "attachment_id": ATTACHMENT_PROP,
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 25, "description": "Neighbours to return (default 8)."},
                    },
                    ["attachment_id"],
                ),
                analyze_waste_image,
            ),
            ToolSpec(
                "assess_image_quality",
                "Check whether an attached photo is good enough as evidence: blur, exposure, resolution and framing "
                "issues, an overall quality score and which additional photos would help.",
                _schema({"attachment_id": ATTACHMENT_PROP}, ["attachment_id"]),
                assess_image_quality,
            ),
            ToolSpec(
                "get_waste_cluster_profile",
                "Describe one unsupervised K-Means cluster of the waste-image dataset: size, purity and the mix of "
                "source categories inside it.",
                _schema({"cluster_id": {"type": "integer", "description": "Cluster id (0-7)."}}, ["cluster_id"]),
                get_waste_cluster_profile,
            ),
            ToolSpec(
                "get_waste_dataset_overview",
                "Summarise the waste-image dataset and its unsupervised model: categories, counts, splits, clustering "
                "quality and known caveats.",
                _schema({}, []),
                get_waste_dataset_overview,
            ),
            ToolSpec(
                "interpret_mineral_spectrum",
                "Interpret an attached VNIR-SWIR reflectance spectrum file (CSV/XLSX, first column wavelength, other "
                "columns spectra, 400-2500 nm) with the mineral engine: absorption features, rule-based mineral "
                "hypotheses, similar reference spectra, spectral cluster, evidence confidence and warnings.",
                _schema({"attachment_id": ATTACHMENT_PROP}, ["attachment_id"]),
                interpret_mineral_spectrum,
            ),
            ToolSpec(
                "get_mineral_model_info",
                "Describe the mineral spectral model: components, input requirements, model card and limitations.",
                _schema({}, []),
                get_mineral_model_info,
            ),
            ToolSpec(
                "search_knowledge_base",
                "Search ScrapTrust's curated reference notes on scrap grades, metal identification, battery and e-waste "
                "safety, recycling processes, hazardous materials, sorting technology, spectroscopy and mineral features, "
                "and on this project (dataset, models, inputs, feedback). Use it to ground factual answers and to answer "
                "questions about the project.",
                _schema(
                    {
                        "query": {"type": "string", "description": "What to look up, in plain words."},
                        "k": {"type": "integer", "minimum": 1, "maximum": 5, "description": "Entries to return (default 3)."},
                    },
                    ["query"],
                ),
                search_knowledge_base,
            ),
        ]
    )
