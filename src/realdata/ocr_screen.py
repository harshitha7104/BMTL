"""Read element values from a photo of an XRF instrument screen or printout (local OCR, no cloud).

PROVENANCE: OCR output is a reading of the photo, never a measurement of the sample. It is returned as
OBSERVED-from-photo values with the OCR confidence, and every value can be checked against the photo.
Two contrast passes are combined; element tiles the full-image passes miss are re-read from a crop to
the left of each still-unlabelled number. Unlabelled numbers are reported, never assigned.
Guards (shared server, untrusted images): pixel cap before decoding (decompression bombs), downscale,
at most MAX_CROPS tile re-reads and a wall-clock budget per photo.
"""

from __future__ import annotations

import io
import time
from functools import lru_cache

import numpy as np
from PIL import Image, ImageOps

from src.realdata.extract import SYMBOLS, pair_ocr_boxes, readings_from_text

Image.MAX_IMAGE_PIXELS = 60_000_000          # refuse decompression bombs
MAX_SIDE = 1280
UPSCALE = 1.5
MAX_CROPS = 12
TIME_BUDGET_S = 20.0


@lru_cache(maxsize=1)
def _engine():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR()


def _boxes(img: Image.Image, scale: float, offset=(0, 0)) -> list[tuple[float, float, str, float]]:
    res, _ = _engine()(np.array(img.convert("RGB")))
    out = []
    for box, text, conf in res or []:
        x = sum(p[0] for p in box) / 4 / scale + offset[0]
        y = sum(p[1] for p in box) / 4 / scale + offset[1]
        out.append((x, y, str(text), float(conf)))
    return out


def read_screen(data: bytes) -> dict:
    start = time.monotonic()
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    img.draft("L", (MAX_SIDE, MAX_SIDE))   # JPEG: decode at reduced size
    gray = img.convert("L")
    f = min(1.0, MAX_SIDE / max(gray.size))
    base = gray.resize((int(gray.width * f), int(gray.height * f))) if f < 1 else gray
    h = base.height
    boxes: list[tuple[float, float, str, float]] = []
    for p in (base, ImageOps.equalize(base)):
        for b in _boxes(p.resize((int(p.width * UPSCALE), int(p.height * UPSCALE))), UPSCALE):
            if not any(abs(b[0] - o[0]) < 0.02 * h and abs(b[1] - o[1]) < 0.02 * h and b[2] == o[2] for o in boxes):
                boxes.append(b)
        if time.monotonic() - start > TIME_BUDGET_S:
            break
    result = pair_ocr_boxes(boxes, h)
    timed_out = False
    for x, y in result["unlabelled_positions"][:MAX_CROPS]:
        if time.monotonic() - start > TIME_BUDGET_S:
            timed_out = True
            break
        x0, x1 = max(0, x - 0.30 * h), max(0, x - 0.04 * h)
        y0, y1 = max(0, y - 0.02 * h), min(h, y + 0.07 * h)
        if x1 - x0 < 10:
            continue
        raw = base.crop((int(x0), int(y0), int(x1), int(y1)))
        target = next((b[2] for b in boxes if abs(b[0] - x) < 2 and abs(b[1] - y) < 2), "")
        # Faint grey element tiles (e.g. a light "Ni" on a grey button) are only found with a contrast stretch. That pass
        # is used only for a value line ("21.86 %"): next to a "± 0.03" uncertainty line it would pair the tile with the
        # uncertainty (seen on 3 of 61 test photos), so those are never labelled from it.
        stretch_ok = "%" in target and "±" not in target
        for strong, crop in ((False, ImageOps.equalize(raw)), (True, ImageOps.autocontrast(raw, cutoff=2))):
            if strong and not stretch_ok:
                continue
            for bx, by, t, c in _boxes(crop.resize((crop.width * 3, crop.height * 3)), 3.0, (x0, y0)):
                if strong and abs(by - y) > 0.03 * h:      # only a label on this number's own row
                    continue
                if t.strip() in SYMBOLS and not any(o[2] == t.strip() and abs(o[1] - by) < 0.03 * h for o in boxes):
                    boxes.append((bx, by, t.strip(), c))
            if time.monotonic() - start > TIME_BUDGET_S:
                break
    if result["unlabelled_positions"]:
        result = pair_ocr_boxes(boxes, h)
    text = "\n".join(t for _, _, t, _ in sorted(boxes, key=lambda b: (round(b[1] / (0.02 * h)), b[0])))
    result.pop("unlabelled_positions", None)
    result["text_readings"] = readings_from_text(text, "photo text")   # printed reports: "Co 15.02 0.04" on one line
    result["ocr_text"] = text[:4000]
    result["mean_confidence"] = round(float(np.mean([b[3] for b in boxes])), 3) if boxes else None
    result["seconds"] = round(time.monotonic() - start, 1)
    result["timed_out"] = timed_out
    return result
