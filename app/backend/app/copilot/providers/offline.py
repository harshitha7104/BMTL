"""
Offline provider: no LLM, no API key.

Runs the relevant domain tools directly and renders a deterministic Markdown
answer from their output:
- photos and video frames  -> dataset similarity + evidence quality
- spectra                  -> mineral interpretation
- audio / video soundtrack -> transcript (used as the question when there is no text)
- text questions           -> scope check, then the curated knowledge base
Off-topic questions get a polite refusal, the same policy the LLM providers follow.
"""
from __future__ import annotations

import re
from typing import List, Optional

from app.copilot.engines.knowledge import OFF_TOPIC_REPLY, KnowledgeBase, classify_scope
from app.copilot.providers.base import ChatProvider, run_tool_calls
from app.copilot.tools import ToolContext, ToolRegistry
from app.copilot.types import Attachment, ChatTurn, ProviderResult, ToolCallRecord

OVERVIEW_PATTERN = re.compile(r"\b(dataset overview|overview of (the|your) dataset|clusters?|categories)\b", re.I)
MINERAL_INFO_PATTERN = re.compile(r"\b(mineral (model|engine)|spectral model)\b", re.I)
# Questions about this assistant / project itself are always in scope.
PROJECT_PATTERN = re.compile(
    r"\b(your|the|this) (dataset|data|model|models|project|app|tool|system|clusters?)\b|\b(scraptrust|this assistant)\b",
    re.I,
)
DEFAULT_PROMPTS = re.compile(r"^please (analyse|respond to) the attached", re.I)
CAPABILITY_PATTERN = re.compile(
    r"\bwhat\b.*\b(can|do) you\b.*\b(identify|detect|name|recogni[sz]e|tell apart)\b"
    r"|\b(list|show)\b.*\b(all|every|the)\b.*\b(materials?|minerals?|metals?|rocks?)\b"
    r"|\b(which|what) (materials?|minerals?|metals?|rocks?)\b.*\b(identify|detect|know|recogni[sz]e|support)\b",
    re.I,
)

INTRO = (
    "Hi! I'm **ScrapTrust**, ACE Green's assistant for battery black mass, scrap and minerals. Here is what I can do:\n\n"
    "- **Check black mass:** type the XRF gun numbers (for example *Ni 31.8 Co 9.1 Mn 9.5*), send a **photo of the gun screen**, "
    "or attach the gun's file (.pdz, CSV, Excel, PDF). I tell you the battery type and estimate nickel, cobalt, manganese and lithium.\n"
    "- **Compare bags and make a report:** after a few readings, say *compare these* or *make a Word report*.\n"
    "- **Identify scrap from a photo** and tell you how to sort it and whether it is hazardous.\n"
    "- **Read a mineral spectrum** file.\n"
    "- **Talk instead of typing:** press the microphone, or **Talk** for a hands-free conversation.\n\n"
    "Things I can't do: measure lithium directly (it is always calculated), replace a lab test, or give prices."
)
OFFLINE_NOTE = "_Answered from ScrapTrust's built-in knowledge base._"


MD_SPECIAL = set("\\`*_[]()<>#|")


def md_safe(text) -> str:
    """Untrusted text (uploaded documents, web pages, transcripts, CSV labels) shown inside an answer: one line, with
    every Markdown control character escaped, so it can never become a link, table, heading or fold-out.
    Security audit N-05: a planted "[Verify your account](https://evil...)" used to render as a clickable link."""
    flat = " ".join(str(text or "").split())
    return "".join("\\" + ch if ch in MD_SPECIAL else ch for ch in flat)


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _material_ok(rec: Optional[ToolCallRecord]) -> bool:
    return rec is not None and not rec.is_error and isinstance(rec.output, dict) and rec.output.get("status") == "ok"


def _render_material(att: Attachment, rec: Optional[ToolCallRecord], waste: ToolCallRecord) -> List[str]:
    if not _material_ok(rec):
        return []
    out = rec.output
    origin = f" (frame from {att.source})" if att.source else ""
    lines = [f"### {att.attachment_id}{origin}: {out['most_likely']}"]
    if not out.get("is_scrap", True):
        lines.append("This doesn't look like scrap, waste, a mineral or a rock. Please upload a clear photo of the material.")
        return lines
    if out.get("headline"):
        lines.append(out["headline"])
    group = out.get("group")
    alts = ", ".join(f"{m['material']} {_pct(m['probability'])}" for m in out.get("top_matches", [])[1:3] if m["probability"] >= 0.01)
    lines.append(
        f"- **Identification:** {out['most_likely']}"
        + (f" ({group}, {_pct(out.get('group_probability', 0))} that it is {group.lower()})" if group else "")
        + f"; {out['confidence']} confidence, {_pct(out['probability'])}."
        + (f" Next closest: {alts}." if alts else "")
    )
    comp = out.get("composition") or {}
    if comp.get("status") == "ok" and comp.get("by_material"):
        parts = [f"{c['material']} {_pct(c['share'])}" for c in comp["by_material"] if c["share"] >= 0.08]
        if comp.get("mixed"):
            lines.append(f"- **Composition (rough, by area):** {', '.join(parts)}.")
        else:
            lines.append(f"- **Composition (rough, by area):** almost entirely {comp['by_material'][0]['material']} "
                         f"({_pct(comp['by_material'][0]['share'])} of {comp.get('tiles_used')} item tiles).")
    colour = out.get("colour") or {}
    if out.get("key") in {"copper", "insulated_wire", "brass", "bronze", "iron", "rusty_steel"} and "copper_coloured" in colour:
        lines.append(
            f"- **Colour check:** {_pct(colour['copper_coloured'])} of the item is copper-coloured, "
            f"{_pct(colour['brass_coloured'])} brass-coloured, {_pct(colour['grey_metallic'])} grey metal."
        )
    w = waste.output if isinstance(waste.output, dict) else {}
    votes = w.get("neighbour_category_votes") or []
    mat_cat = (out.get("top_matches") or [{}])[0].get("dataset_category")
    if w.get("status") == "ok" and votes and mat_cat:
        if votes[0]["category"] == mat_cat:
            lines.append(f"- **Dataset check:** consistent; the most similar dataset photos are mostly *{mat_cat}*.")
        else:
            lines.append(f"- **Dataset check:** the most similar dataset photos lean *{votes[0]['category']}*, so treat the name with care.")
    lines.append(f"- **What to do:** {out['guidance']}")
    return lines


def _render_waste(att: Attachment, rec: ToolCallRecord, heading: bool = True) -> List[str]:
    out = rec.output if isinstance(rec.output, dict) else {}
    origin = f" (frame from {att.source})" if att.source else ""
    lines = [f"### {att.attachment_id}{origin}: dataset similarity" if heading else "**Dataset similarity (supporting evidence)**"]
    if rec.is_error or out.get("status") != "ok":
        lines.append(f"- Similarity search unavailable: {out.get('reason') or out.get('error') or 'unknown error'}")
        if out.get("hint"):
            lines.append(f"- {out['hint']}")
        return lines
    votes = out.get("neighbour_category_votes", [])[:3]
    if votes:
        lines.append(
            "- **Closest source categories:** "
            + ", ".join(f"{v['category']} ({_pct(v['weighted_share'])})" for v in votes)
            + f", agreement **{out.get('neighbour_agreement')}**"
        )
    lines.append(f"- **Max similarity:** {out.get('max_similarity')} ({str(out.get('novelty', '')).replace('_', ' ')})")
    cluster = out.get("nearest_cluster")
    if cluster:
        comp = ", ".join(f"{c['category']} {_pct(c['share'])}" for c in cluster.get("source_category_composition", [])[:3])
        lines.append(f"- **Nearest unsupervised cluster:** #{cluster['cluster_id']} (size {cluster['size']}; {comp})")
    return lines


def _render_quality(rec: ToolCallRecord) -> List[str]:
    out = rec.output if isinstance(rec.output, dict) else {}
    if rec.is_error:
        return [f"- Image quality check failed: {out.get('error')}"]
    lines = [f"- **Evidence quality:** {out.get('status')} (score {out.get('overall_score')}/100)"]
    for issue in (out.get("issues") or [])[:3]:
        lines.append(f"  - {issue.get('severity')}: {issue.get('description')}")
    return lines


def _render_mineral(att: Attachment, rec: ToolCallRecord) -> List[str]:
    out = rec.output if isinstance(rec.output, dict) else {}
    lines = [f"### {att.attachment_id}: spectral interpretation"]
    if rec.is_error or out.get("status") != "ok":
        lines.append(f"- Mineral engine unavailable: {out.get('error') or out.get('reason')}")
        return lines
    for res in out.get("results", []):
        lines.append(
            f"- **{res.get('sample', 'spectrum')}:** {res.get('prediction')} "
            f"(type {res.get('prediction_type')}, evidence confidence {res.get('confidence')})"
        )
        for warning in (res.get("warnings") or [])[:2]:
            lines.append(f"  - ⚠ {warning}")
    if out.get("spectra_in_file", 0) > out.get("spectra_reported", 0):
        lines.append(f"- Showing {out['spectra_reported']} of {out['spectra_in_file']} spectra.")
    return lines


NAMES = {"Ni": "nickel", "Co": "cobalt", "Mn": "manganese", "Fe": "iron", "Cu": "copper", "Al": "aluminium", "P": "phosphorus",
         "Li": "lithium", "Si": "silicon", "S": "sulphur", "Ca": "calcium", "Ti": "titanium", "Cr": "chromium", "Zn": "zinc",
         "Mg": "magnesium", "Pb": "lead"}
MATERIAL_WORDS = {"NMC": "NMC black mass (nickel-manganese-cobalt batteries)", "LFP": "LFP black mass (lithium iron phosphate batteries)",
                  "LCO": "LCO black mass (lithium cobalt oxide batteries)", "NCA": "NCA black mass (nickel-cobalt-aluminium batteries)",
                  "LMO": "LMO black mass (lithium manganese oxide batteries)"}


def _r(x) -> str:
    """Round for people: 1 decimal (2 below 1 %), no trailing noise."""
    if x is None:
        return "-"
    x = float(x)
    return f"{x:.2f}" if abs(x) < 1 else f"{x:.1f}"


def _sure(conf) -> str:
    if not isinstance(conf, (int, float)):
        return "unknown confidence"
    return "high confidence" if conf >= 0.8 else "medium confidence" if conf >= 0.5 else "low confidence"


def _verdict(view: dict) -> List[str]:
    """Plain-language answer first: what it is, the main metals, how sure, what to do next."""
    material = view.get("material") or {}
    label = material.get("label") or "UNKNOWN"
    compound = (view.get("compound") or {}).get("name")
    els = view.get("elements") or {}
    main = []
    for e in ("Ni", "Co", "Mn", "Fe"):
        v = ((els.get(e) or {}).get("inferred") or {}).get("value_pct")
        if v is not None and float(v) >= 1:
            main.append(f"{NAMES[e]} about {_r(v)} %")
    li = (view.get("lithium") or {}).get("value_pct")
    if label.startswith("NOT_BLACK_MASS"):
        what = "This does **not** look like battery black mass (" + label.replace("NOT_BLACK_MASS_", "").replace("_", " ").lower() + ")."
    elif label in ("UNKNOWN", "ABSTAIN", None):
        what = "I can't tell which battery type this black mass comes from."
    else:
        what = f"This looks like **{MATERIAL_WORDS.get(label, label + ' black mass')}**" + (f", most likely **{compound.split(' (')[0]}**" if compound else "") + f" ({_sure(material.get('confidence'))})."
    lines = [f"**In short:** {what}"]
    if main:
        lines.append("Estimated content: " + ", ".join(main) + (f", lithium about {_r(li)} % (calculated, not measured)." if li is not None else "."))
    lines.append("These are estimates from a handheld XRF gun. **Send a sample to the lab (ICP-OES) before you buy, sell or price it.**")
    return lines


def _render_view(view: dict, observed_label: str) -> List[str]:
    lines: List[str] = _verdict(view) + [""]
    material = view.get("material") or {}
    compound = view.get("compound") or {}
    lines.append(f"| Element | {observed_label} | Lab-equivalent estimate (INFERRED) | Likely range (90 %) |")
    lines.append("|---|---|---|---|")
    for element, entry in (view.get("elements") or {}).items():
        obs = (entry.get("observed") or {}).get("value_pct")
        inf = entry.get("inferred") or {}
        est = inf.get("value_pct")
        if obs is None and est is None:
            continue
        band = f"{_r(inf['low'])} - {_r(inf['high'])}" if est is not None and inf.get("low") is not None else (inf.get("reason") or "UNKNOWN")
        name = f"{element} ({NAMES[element]})" if element in NAMES else element
        lines.append(f"| {name} | {'' if obs is None else _r(obs)} | {'UNKNOWN' if est is None else _r(est)} | {band} |")
    li = view.get("lithium") or {}
    if li.get("value_pct") is not None:
        lines.append(f"| Li (lithium) | cannot be measured by XRF | {_r(li['value_pct'])} (calculated) | {_r(li['low'])} - {_r(li['high'])} |")
    lines.append("")
    details = [f"material {material.get('label')} ({material.get('state')}, score {material.get('confidence')}, decided by {material.get('decided_by')})"]
    if compound.get("name"):
        details.append(f"compound {compound['name']} ({compound.get('basis')})")
    lines.append("<details><summary>How this was worked out</summary>\n\n"
                 "OBSERVED = what the gun read. INFERRED = the model's estimate of what a lab would measure. "
                 "Range = where the lab value is likely to fall (90 % of the time). Details: " + "; ".join(details) + ".\n\n</details>")
    lines.append("")
    return lines


def _friendly_label(label) -> str:
    label = str(label or "Reading")
    if label.startswith("message text reading"):
        return "Reading " + label.rsplit(" ", 1)[-1]
    return md_safe(label)          # labels come from user files (CSV cells, sheet names)


def _render_black_mass(att: Attachment, rec: ToolCallRecord) -> List[str]:
    out = rec.output if isinstance(rec.output, dict) else {}
    if rec.is_error:
        return ["### Black-mass check", f"- Sorry, the black-mass check could not run: {out.get('error')}. Please try again; if it keeps failing, contact your ScrapTrust administrator."]
    if "results" in out:
        n = out.get("readings_found") or 0
        source = "your message" if att.attachment_id == "message" else att.filename
        lines = [f"### Black-mass check: {n} reading{'s' if n != 1 else ''} found in {source}"]
        if out.get("photo_reading"):
            pr = out["photo_reading"]
            lines.append(f"- I read these numbers from your photo (reading confidence {pr.get('mean_ocr_confidence')}). **Please check them against the screen in the photo.**")
            if pr.get("unlabelled_numbers_not_used"):
                lines.append(f"- Numbers I could not match to an element, so I did not use them: {pr['unlabelled_numbers_not_used']}")
        for r in out["results"][:5]:
            if r.get("status") == "NOT_ASSESSED":
                lines.append(f"**{_friendly_label(r.get('label'))}**: not checked ({r.get('reason')})")
                continue
            if n > 1:
                lines.append(f"#### {_friendly_label(r.get('label'))}")
            lines += _render_view(r, "Gun reading (OBSERVED)")
        if out.get("note"):
            lines.append(f"- {out['note']}")
        lines.append("_The models were trained on 9 lab-tested ACE samples, so treat every estimate as a guide, not a lab result._")
        return lines
    if out.get("status") == "photo could not be read reliably":
        return ["### Black-mass check: photo of an XRF screen",
                f"- I couldn't read the numbers reliably ({out.get('reason')}).",
                "- Try: hold the phone straight above the screen, avoid glare, fill the frame with the numbers, or type the values instead, for example `Ni 31.8 Co 9.1 Mn 9.5`."]
    if "factory_calibration" not in out:
        return []   # nothing element-like in this input; other tools describe it
    lines = [f"### Black-mass check: {out.get('file', att.filename)}"]
    view = out.get("factory_calibration") or {}
    lines += _render_view(view, "Gun reading (OBSERVED)")
    lines.append("_The models were trained on 9 lab-tested ACE samples, so treat every estimate as a guide, not a lab result._")
    return lines


REPORT_PATTERN = re.compile(r"\b(report|word|docx|document it|write[- ]?up|summary file|share(able)?)\b", re.I)
LOT_PATTERN = re.compile(r"\b(compare|comparison|lot|batch|outliers?|odd|consistent|which (one|sample|bag)s?.*(icp|lab)|send .*(icp|lab))\b", re.I)
INTAKE_NOTES = re.compile(r"\[Intake notes: (.*?)\]\s*$", re.S)
ELEMENT_VALUE = re.compile(r"\b(Ni|Co|Mn|Fe|Cu|Al|P|Li|Pb|Zn|nickel|cobalt|manganese|iron|copper|aluminium|aluminum|lithium|lead)\b\s*[:=]?\s*\d+(?:[.,]\d+)?", re.I)


def _render_lot(out: dict) -> List[str]:
    if out.get("status") != "ok":
        return [f"**Lot analysis:** {out.get('message') or out.get('note') or 'not enough readings yet.'}"]
    lines = [f"**Lot analysis ({out.get('readings')} readings)**", "", "| Element | n | Mean | Min – max | Spread |", "|---|---|---|---|---|"]
    for e, s in (out.get("per_element") or {}).items():
        spread = f"{s['spread_pct']} %" if s.get("spread_pct") is not None else "–"
        lines.append(f"| {e} | {s['n']} | {s['mean']:g} | {s['min']:g} – {s['max']:g} | {spread} |")
    groups = out.get("chemistry_groups") or {}
    if groups:
        lines.append("")
        lines.append("- Chemistry: " + "; ".join(f"{md_safe(g)}: {', '.join(_friendly_label(x) for x in v)}" for g, v in groups.items())
                     + (" (consistent)" if out.get("chemistry_consistent") else " (**mixed lot**)"))
    for o in out.get("outliers") or []:
        lines.append(f"- Outlier: {_friendly_label(o['label'])} {o['element']} {o['value']} % (lot median {o['lot_median']} %)")
    for p in out.get("send_for_icp_first") or []:
        lines.append(f"- Send for ICP-OES first: **{_friendly_label(p['label'])}** ({md_safe(p['why'])})")
    if out.get("note"):
        lines.append(f"- {out['note']}")
    return lines


def _render_media(att: Attachment) -> List[str]:
    if att.kind in {"audio", "video"}:
        title = "voice / audio" if att.kind == "audio" else "video soundtrack"
        lines = [f"### {att.attachment_id}: {title}"]
        if att.text:
            lines.append(f"> {md_safe(att.text)}")
        else:
            lines.append(f"- No transcript: {att.note or 'no speech detected'}.")
        return lines
    if att.kind == "document":
        lines = [f"### {att.attachment_id}: document `{att.filename}`"]
        if att.text:
            preview = " ".join(att.text.split())[:400]
            lines += [f"- Read {md_safe(att.note)}.", f"> {md_safe(preview)}{'...' if len(att.text) > 400 else ''}"]
        else:
            lines.append(f"- {att.note or 'No extractable text.'}")
        return lines
    return []


def _render_kb(hits: List[dict]) -> List[str]:
    if not hits:
        return ["I couldn't find this in the knowledge base."]
    top = hits[0]
    lines = [f"**{top['title']}**", "", top["text"]]
    related = [h["title"] for h in hits[1:] if h["score"] >= 0.6 * top["score"]]
    if related:
        lines += ["", "Related topics: " + "; ".join(related)]
    return lines


class OfflineProvider(ChatProvider):
    name = "offline"
    display_name = "Built-in (private)"
    supports_vision = False

    def __init__(self, knowledge_base: Optional[KnowledgeBase] = None) -> None:
        self._kb = knowledge_base or KnowledgeBase()

    @property
    def model(self) -> str:
        return "knowledge-base + engines"

    def is_configured(self) -> bool:
        return True

    async def respond(
        self,
        *,
        system: str,
        history: List[ChatTurn],
        user_turn: ChatTurn,
        images: List[Attachment],
        tools: ToolRegistry,
        ctx: ToolContext,
        max_rounds: int,
    ) -> ProviderResult:
        current = [ctx.attachments[a] for a in user_turn.attachment_ids if a in ctx.attachments]

        # The question: typed text, or the transcript of a voice message when no text was typed.
        typed = "" if DEFAULT_PROMPTS.match(user_turn.text) else user_turn.text.strip()
        intake = INTAKE_NOTES.search(typed)
        if intake:   # notes added by the server about links/folders: shown to the user, not part of the question
            typed = INTAKE_NOTES.sub("", typed).strip()
        spoken = " ".join(a.text for a in current if a.kind == "audio" and a.text)
        question = typed or spoken

        calls: List[tuple[str, dict]] = []
        values_in_text = bool(question) and len({m.group(1).lower() for m in ELEMENT_VALUE.finditer(question)}) >= 2
        if values_in_text:
            calls.append(("assess_black_mass_xrf", {"text": question}))
        for att in current:
            if att.kind in ("image", "document", "audio", "video"):
                calls.append(("assess_black_mass_xrf", {"attachment_id": att.attachment_id}))
            if att.kind == "image":
                calls += [("identify_material", {"attachment_id": att.attachment_id}),
                          ("assess_image_quality", {"attachment_id": att.attachment_id}),
                          ("analyze_waste_image", {"attachment_id": att.attachment_id, "top_k": 8})]
            elif att.kind == "spectrum":
                calls.append(("interpret_mineral_spectrum", {"attachment_id": att.attachment_id}))
            elif att.kind == "xrf":
                calls.append(("assess_black_mass_xrf", {"attachment_id": att.attachment_id}))

        analysable = any(a.kind in {"image", "spectrum", "document", "video", "xrf"} for a in current)
        has_readings = bool(ctx.results) or any(n == "assess_black_mass_xrf" for n, _ in calls)
        wants_report = bool(question) and bool(REPORT_PATTERN.search(question)) and has_readings
        wants_lot = bool(question) and bool(LOT_PATTERN.search(question)) and has_readings
        agent_calls: List[tuple[str, dict]] = []
        if wants_lot or wants_report:
            agent_calls.append(("analyse_lot", {}))
        if wants_report:
            agent_calls.append(("write_assessment_report", {}))
        about_project = bool(question) and bool(
            PROJECT_PATTERN.search(question) or OVERVIEW_PATTERN.search(question) or MINERAL_INFO_PATTERN.search(question)
            or CAPABILITY_PATTERN.search(question)
        )
        if about_project:
            scope = "in_scope"
        elif question:
            scope = classify_scope(question, self._kb)
        else:
            scope = "in_scope" if analysable else "small_talk"
        if values_in_text or agent_calls:
            pass   # the typed/spoken element values (or the agents' work) are the subject: no knowledge-base lookup needed
        elif question and not analysable:
            heard = [l for a in current for l in _render_media(a)]  # show what was transcribed
            prefix = "\n".join(heard) + "\n\n" if heard else ""
            if scope == "off_topic":
                return ProviderResult(prefix + OFF_TOPIC_REPLY, self.name, self.model, [], stop_reason="off_topic")
            if scope == "small_talk":
                return ProviderResult(prefix + INTRO, self.name, self.model, [], stop_reason="end_turn")
            if CAPABILITY_PATTERN.search(question):
                calls.append(("list_identifiable_materials", {}))
            elif MINERAL_INFO_PATTERN.search(question):
                calls.append(("get_mineral_model_info", {}))
            elif OVERVIEW_PATTERN.search(question):
                calls.append(("get_waste_dataset_overview", {}))
            else:
                calls.append(("search_knowledge_base", {"query": question, "k": 3}))
        elif question and analysable and scope == "in_scope" and not any(a.kind == "image" for a in current):
            # e.g. a document plus a question: also look the question up.
            calls.append(("search_knowledge_base", {"query": question, "k": 2}))

        records = await run_tool_calls(tools, calls, ctx) if calls else []
        # the lot-analyst / report-writer agents run after this turn's readings exist
        agent_records = [await tools.execute(n, a, ctx) for n, a in agent_calls]
        by_att: dict = {}
        general: List[ToolCallRecord] = []
        for (name, args), rec in zip(calls, records):
            if "attachment_id" in args:
                by_att.setdefault(args["attachment_id"], {})[name] = rec
            else:
                general.append(rec)

        lines: List[str] = []
        caveats: List[str] = []
        if intake:
            lines += ["**What I could and could not open**", *[f"- {md_safe(n.strip())}" for n in intake.group(1).split(";") if n.strip()], ""]
        for rec in [r for r in general if r.name == "assess_black_mass_xrf"]:
            pseudo = Attachment("message", "document", "your message", "text/plain", "", 0)
            lines += _render_black_mass(pseudo, rec) + [""]
        general = [r for r in general if r.name != "assess_black_mass_xrf"]
        for att in current:
            recs = by_att.get(att.attachment_id, {})
            bm = recs.get("assess_black_mass_xrf")
            bm_found = att.kind != "xrf" and bm is not None and isinstance(bm.output, dict) and bool(bm.output.get("results"))
            if bm_found:   # an instrument reading in a photo/document is the most specific evidence: show it first
                lines += _render_black_mass(att, bm)
            if att.kind == "image":
                waste = recs["analyze_waste_image"]
                material = recs.get("identify_material")
                lines += _render_material(att, material, waste)
                lines += _render_waste(att, waste, heading=material is None or not _material_ok(material))
                lines += _render_quality(recs["assess_image_quality"])
                for rec in (material, waste):
                    if rec is not None and isinstance(rec.output, dict):
                        caveats += rec.output.get("caveats", [])
            elif att.kind == "spectrum":
                rec = recs["interpret_mineral_spectrum"]
                lines += _render_mineral(att, rec)
                if isinstance(rec.output, dict):
                    caveats += rec.output.get("caveats", [])
            elif att.kind == "xrf":
                lines += _render_black_mass(att, recs["assess_black_mass_xrf"])
            else:
                lines += _render_media(att)
            if att.kind != "xrf" and bm is not None and not bm_found:
                lines += _render_black_mass(att, bm)
            lines.append("")

        for rec in general:
            out = rec.output if isinstance(rec.output, dict) else {}
            if rec.is_error:
                lines.append(f"Tool error: {out.get('error')}")
            elif rec.name == "search_knowledge_base":
                if scope == "off_topic":
                    lines.append(OFF_TOPIC_REPLY)
                else:
                    lines += _render_kb(out.get("results", [])) + ["", OFFLINE_NOTE]
            elif rec.name == "get_waste_dataset_overview":
                cats = ", ".join(f"{k} ({v})" for k, v in out.get("source_categories", {}).items())
                clus = out.get("clustering", {})
                sil = clus.get("silhouette")
                lines += [
                    f"The waste dataset has **{out.get('image_count')} images** embedded with {out.get('embedding_model')}.",
                    f"- Source categories: {cats}",
                    f"- Unsupervised clustering: {clus.get('method')} k={clus.get('k')}, silhouette "
                    + (f"{sil:.3f}" if isinstance(sil, (int, float)) else "n/a"),
                ]
                caveats += out.get("caveats", [])
            elif rec.name == "get_mineral_model_info":
                lines += ["**Mineral spectral model**"] + [f"- {c}" for c in out.get("components", [])]
                lines.append(f"- Input: {out.get('input_requirements')}")
                caveats += out.get("caveats", [])
            elif rec.name == "list_identifiable_materials":
                lines.append(
                    f"I can name **{out.get('total')} materials, minerals and rocks** in photos. Upload one and I'll "
                    "tell you what it is, plus a rough composition for mixed loads:"
                )
                for group, names in (out.get("by_group") or {}).items():
                    lines.append(f"- **{group}:** {', '.join(names)}")
                lines.append(
                    "\nFor minerals, a reflectance spectrum (CSV/XLSX, 400–2500 nm) gives a stronger identification "
                    "than a photo."
                )

        for rec in agent_records:
            out = rec.output if isinstance(rec.output, dict) else {}
            if rec.is_error:
                lines.append(f"{rec.name}: {out.get('error')}")
            elif rec.name == "analyse_lot":
                lines += _render_lot(out)
            elif rec.name == "write_assessment_report":
                lines += ["", f"**Report ready:** {out['report']['filename']} ({out.get('readings_in_report')} reading(s)). "
                          "Download it from the button under this answer."]
        records = records + agent_records

        if not lines:
            lines = [INTRO]
        if caveats:
            lines += ["**Caveats**"] + [f"- {c}" for c in dict.fromkeys(caveats)]
        return ProviderResult(
            text="\n".join(lines).strip(), provider=self.name, model=self.model, tool_calls=records, stop_reason="end_turn"
        )
