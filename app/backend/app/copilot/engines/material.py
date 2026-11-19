"""
Zero-shot material identification for scrap, waste, mineral and rock photos.

The waste dataset only has nine broad folders ("metal waste", "E-waste", ...),
so dataset similarity can never say "copper", "PET" or "quartz". This engine
names the material directly with a pretrained CLIP vision-language model: the
photo is compared with text descriptions of every entry in the catalogue
(material_catalog.py; several phrasings each, averaged). No training data or
labels are involved, so new materials are added by writing descriptions.

The answer has two levels: the group ("Metal", "Plastic", "Mineral", ...) and
the specific material ("Copper", "PET plastic bottles", "Pyrite"). When the
specific name is uncertain, the headline falls back to the group.

For mixed loads, the photo is also split into tiles that are identified
separately, giving a rough composition by area ("about 70% copper, 20% brass").
A colour analysis (copper-, brass- or grey-metal-coloured share of the item) is
reported as supporting evidence.

Neither CLIP nor colour can determine alloy grade, purity or chemistry.
"""
from __future__ import annotations

import io
import logging
import threading
from typing import Dict, List, Optional

import numpy as np

from app.copilot.engines.material_catalog import MATERIALS, Material, catalogue_by_group  # noqa: F401 (re-exported)

log = logging.getLogger(__name__)

TEMPLATES = ("a photo of {}.", "a close-up photo of {}.")
GRID = 3                 # composition tiles per side
MIN_TILE_ITEM = 0.30     # a tile counts only if at least 30% of it is the item (not background)

GROUP_PHRASE = {
    "Metal": "metal", "Mineral": "a mineral", "Rock": "a rock", "Plastic": "plastic", "Glass": "glass",
    "Paper": "paper", "Electronics": "electronic waste", "Battery": "a battery", "Lamp": "a lamp",
    "Automotive": "automotive scrap", "Organic": "organic waste", "Construction material": "a construction material",
    "Other material": "another material",
}

CAVEATS = [
    "Names come from a general-purpose vision-language model (CLIP) compared with written descriptions; "
    "no ScrapTrust-specific training.",
    "Appearance cannot confirm alloy grade, purity, chemistry or mineral identity with certainty; rust, paint, "
    "lighting and look-alikes can mislead. Confirm with a magnet test, XRF/LIBS, or for minerals XRD or spectroscopy.",
]


def _foreground_mask(rgb: np.ndarray, hsv: np.ndarray) -> np.ndarray:
    """Pixels that belong to the item: differ from the border colour and aren't blown-out white or black."""
    s, v = hsv[..., 1], hsv[..., 2]
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    bg = np.median(border, axis=0)
    dist = np.linalg.norm(rgb - bg, axis=-1)
    return (dist > 40) & (v > 0.12) & ~((s < 0.08) & (v > 0.92))


def colour_profile(image_bytes: bytes) -> dict:
    """Share of the item's pixels that look copper-, brass- or grey-metal-coloured (background removed)."""
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as im:
        im = im.convert("RGB")
        im.thumbnail((160, 160))
        hsv = np.asarray(im.convert("HSV"), dtype=np.float32) / 255.0
        rgb = np.asarray(im, dtype=np.float32)
    h, s, v = hsv[..., 0] * 360.0, hsv[..., 1], hsv[..., 2]
    foreground = _foreground_mask(rgb, hsv)
    n = int(foreground.sum())
    if n < 0.02 * foreground.size:
        foreground = np.ones_like(foreground)
        n = foreground.size

    copper = foreground & (h >= 5) & (h <= 32) & (s >= 0.35) & (v >= 0.25)
    brass = foreground & (h > 32) & (h <= 58) & (s >= 0.30) & (v >= 0.35)
    grey = foreground & (s < 0.15) & (v >= 0.25) & (v <= 0.9)
    shares = {
        "copper_coloured": round(float(copper.sum()) / n, 3),
        "brass_coloured": round(float(brass.sum()) / n, 3),
        "grey_metallic": round(float(grey.sum()) / n, 3),
    }
    dominant = max(shares, key=shares.get)
    return {
        "item_pixel_share": round(n / foreground.size, 3),
        **shares,
        "dominant": dominant if shares[dominant] >= 0.25 else "mixed",
        "note": "Reddish-orange hues also occur with rust, wood and cardboard; use as supporting evidence only.",
    }


def _confidence(p1: float, p2: float) -> str:
    if p1 >= 0.55 and p1 - p2 >= 0.25:
        return "high"
    if p1 >= 0.30:
        return "moderate"
    return "low"


def _headline(best: Material, conf: str, group: str, group_p: float, runners: List[Material]) -> str:
    if best.key == "not_scrap":
        return "This doesn't look like scrap, waste, a mineral or a rock."
    phrase = GROUP_PHRASE.get(group, group.lower())
    if conf == "high":
        return f"It is **{best.name}** ({phrase})."
    if conf == "moderate":
        return f"It is **{phrase}**, most likely **{best.name}**."
    if group_p >= 0.5:
        others = ", ".join(m.name for m in runners[:2])
        return f"It is **{phrase}**; the exact type is uncertain (closest: {best.name}, {others})."
    names = ", ".join(f"**{m.name}**" for m in [best, *runners[:2]])
    return f"It is uncertain; it looks most like {names}."


class MaterialIdentifier:
    """Lazy CLIP wrapper; text embeddings for the whole catalogue are computed once."""

    def __init__(self, model_id: str = "openai/clip-vit-base-patch16", device: str = "auto") -> None:
        self.model_id = model_id
        self.device_pref = device
        self._model = None
        self._processor = None
        self._text = None
        self._device = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ loading
    def _load(self):
        with self._lock:
            if self._model is not None:
                return
            try:
                import torch
                from transformers import CLIPModel, CLIPProcessor
            except ImportError as exc:
                raise RuntimeError("Material identification needs torch and transformers; install backend/requirements-copilot.txt") from exc
            device = self.device_pref
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            log.info("Loading material model %s on %s", self.model_id, device)
            from app.core.models_safe import load_clip

            model, processor = load_clip(self.model_id)   # pinned revision, local cache only unless downloads are allowed
            model = model.eval().to(device)
            embeds = []
            with torch.inference_mode():
                for m in MATERIALS:
                    texts = [t.format(p) for p in m.prompts for t in TEMPLATES]
                    tok = processor(text=texts, return_tensors="pt", padding=True).to(device)
                    t = model.get_text_features(**tok)
                    t = t if isinstance(t, torch.Tensor) else t.pooler_output
                    t = torch.nn.functional.normalize(t, dim=-1).mean(dim=0)
                    embeds.append(torch.nn.functional.normalize(t, dim=-1))
            self._text = torch.stack(embeds)
            self._model, self._processor, self._device = model, processor, device
            log.info("Material model ready: %d catalogue entries", len(MATERIALS))

    def warm_up(self) -> None:
        """Load the model ahead of the first request (safe to call from a background thread)."""
        try:
            self._load()
        except Exception as exc:
            log.warning("Material model warm-up failed: %s", exc)

    # ---------------------------------------------------------------- scoring
    def _probs(self, images: list) -> np.ndarray:
        """Probabilities per catalogue entry for a batch of PIL images -> (n_images, n_materials)."""
        import torch

        self._load()
        with torch.inference_mode():
            pix = self._processor(images=images, return_tensors="pt").to(self._device)
            img = self._model.get_image_features(**pix)
            img = img if isinstance(img, torch.Tensor) else img.pooler_output
            img = torch.nn.functional.normalize(img, dim=-1)
            logits = self._model.logit_scale.exp() * img @ self._text.T
            return logits.softmax(dim=-1).float().cpu().numpy()

    def scores(self, image_bytes: bytes) -> np.ndarray:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as im:
            rgb = im.convert("RGB")
        return self._probs([rgb])[0]

    def composition(self, image) -> dict:
        """Rough composition by area: identify GRID x GRID tiles that mostly show the item."""
        from PIL import Image

        im = image.copy()
        im.thumbnail((672, 672))
        small = im.copy()
        small.thumbnail((160, 160))
        rgb = np.asarray(small, dtype=np.float32)
        hsv = np.asarray(small.convert("HSV"), dtype=np.float32) / 255.0
        fg = _foreground_mask(rgb, hsv)
        H, W = fg.shape
        tiles, weights = [], []
        for r in range(GRID):
            for c in range(GRID):
                y0, y1 = r * H // GRID, (r + 1) * H // GRID
                x0, x1 = c * W // GRID, (c + 1) * W // GRID
                share = float(fg[y0:y1, x0:x1].mean()) if (y1 > y0 and x1 > x0) else 0.0
                if share < MIN_TILE_ITEM:
                    continue
                box = (c * im.width // GRID, r * im.height // GRID, (c + 1) * im.width // GRID, (r + 1) * im.height // GRID)
                tiles.append(im.crop(box))
                weights.append(share)
        if len(tiles) < 3:
            return {"status": "not_applicable", "reason": "item fills too little of the photo to split it"}
        probs = self._probs(tiles)
        scrap = np.array([m.key != "not_scrap" for m in MATERIALS])
        by_material: Dict[str, float] = {}
        by_group: Dict[str, float] = {}
        for p, w in zip(probs, weights):
            idx = int(np.argmax(np.where(scrap, p, -1)))
            m = MATERIALS[idx]
            by_material[m.name] = by_material.get(m.name, 0.0) + w
            by_group[m.group] = by_group.get(m.group, 0.0) + w
        total = sum(weights)
        materials = sorted(((k, v / total) for k, v in by_material.items()), key=lambda kv: -kv[1])
        groups = sorted(((k, v / total) for k, v in by_group.items()), key=lambda kv: -kv[1])
        return {
            "status": "ok",
            "tiles_used": len(tiles),
            "by_material": [{"material": k, "share": round(v, 2)} for k, v in materials],
            "by_group": [{"group": k, "share": round(v, 2)} for k, v in groups],
            "mixed": len(materials) > 1 and materials[1][1] >= 0.2,
            "note": "Rough estimate by photo area from separately identified tiles, not by weight.",
        }

    def identify(self, image_bytes: bytes, top_k: int = 5) -> dict:
        from PIL import Image

        try:
            with Image.open(io.BytesIO(image_bytes)) as im:
                rgb = im.convert("RGB")
            probs = self._probs([rgb])[0]
        except Exception as exc:
            log.warning("Material identification failed: %s", exc)
            return {"status": "unavailable", "reason": str(exc)}

        order = np.argsort(-probs)
        best = MATERIALS[order[0]]
        p1, p2 = float(probs[order[0]]), float(probs[order[1]])
        groups: Dict[str, float] = {}
        for m, p in zip(MATERIALS, probs):
            groups[m.group] = groups.get(m.group, 0.0) + float(p)
        group_p = groups[best.group]
        conf = _confidence(p1, p2)
        runners = [MATERIALS[i] for i in order[1:4]]

        try:
            colour = colour_profile(image_bytes)
        except Exception as exc:  # optional supporting evidence
            colour = {"error": str(exc)}
        try:
            comp = self.composition(rgb) if best.key != "not_scrap" else {"status": "not_applicable"}
        except Exception as exc:
            comp = {"status": "error", "reason": str(exc)}

        return {
            "status": "ok",
            "headline": _headline(best, conf, best.group, group_p, runners),
            "most_likely": best.name,
            "key": best.key,
            "group": best.group,
            "group_probability": round(group_p, 3),
            "family": best.family,
            "confidence": conf,
            "probability": round(p1, 3),
            "top_matches": [
                {
                    "material": MATERIALS[i].name,
                    "key": MATERIALS[i].key,
                    "group": MATERIALS[i].group,
                    "family": MATERIALS[i].family,
                    "probability": round(float(probs[i]), 3),
                    "dataset_category": MATERIALS[i].dataset_category,
                }
                for i in order[: max(1, min(top_k, 10))]
            ],
            "group_probabilities": {k: round(v, 3) for k, v in sorted(groups.items(), key=lambda kv: -kv[1]) if v >= 0.005},
            "composition": comp,
            "colour": colour,
            "guidance": best.guidance,
            "knowledge_topic": best.kb_query,
            "is_scrap": best.key != "not_scrap",
            "model": self.model_id,
            "caveats": CAVEATS,
        }
