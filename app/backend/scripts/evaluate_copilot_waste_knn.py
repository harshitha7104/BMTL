"""Measure how often the copilot's neighbour vote agrees with the (unverified) folder category.

1. Leave-one-out over all 11,521 stored vectors, ignoring the image itself and any
   near-duplicate (cosine >= 0.995) so duplicated files cannot inflate the score.
2. 300 random images re-embedded live on the GPU after crop + rotation + JPEG re-encode,
   with near-duplicates of the source excluded the same way.
Writes data/evaluations/phase4/copilot_waste_knn_eval.json. Run from backend/: python scripts/evaluate_copilot_waste_knn.py
"""
import io
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable

import numpy as np
from PIL import Image

from app.core.config import settings
from app.copilot.engines.waste import WasteSimilarityIndex, resolve_dataset_file

K = 8
OUT = Path(__file__).resolve().parents[2] / "data" / "evaluations" / "phase4" / "copilot_waste_knn_eval.json"
OUT.parent.mkdir(parents=True, exist_ok=True)
DUP = 0.995
index = WasteSimilarityIndex(settings.embeddings_path)
index.load()
V = index.vectors
cats = np.array([r.category for r in index.records])
names = sorted(set(cats))


def vote(sims: np.ndarray, exclude: np.ndarray) -> tuple[str, float]:
    sims = sims.copy()
    sims[exclude] = -np.inf
    top = np.argpartition(-sims, K)[:K]
    scores = defaultdict(float)
    for j in top:
        scores[cats[j]] += max(float(sims[j]), 0.0)
    best = max(scores, key=scores.get)
    return best, scores[best] / (sum(scores.values()) or 1.0)


# 1) leave-one-out
t = time.time()
loo_hits, per_cat, conf = 0, Counter(), defaultdict(Counter)
agree_bins = {"strong": [0, 0], "moderate": [0, 0], "weak": [0, 0]}
for start in range(0, len(V), 1024):
    block = V[start:start + 1024] @ V.T
    for r, sims in enumerate(block):
        i = start + r
        pred, share = vote(sims, sims >= DUP)
        hit = pred == cats[i]
        loo_hits += hit
        per_cat[cats[i]] += hit
        conf[cats[i]][pred] += 1
        b = "strong" if share >= 0.75 else "moderate" if share >= 0.5 else "weak"
        agree_bins[b][0] += hit
        agree_bins[b][1] += 1
cat_totals = Counter(cats)
loo = {
    "images": len(V),
    "top1_agreement": round(loo_hits / len(V), 4),
    "per_category_agreement": {c: round(per_cat[c] / cat_totals[c], 3) for c in names},
    "agreement_by_confidence_band": {
        b: {"images": n, "share_of_images": round(n / len(V), 3), "agreement": round(h / n, 3) if n else None}
        for b, (h, n) in agree_bins.items()
    },
    "most_confused_pairs": [
        {"true": a, "predicted": p, "count": n}
        for (a, p), n in Counter({(a, p): n for a in conf for p, n in conf[a].items() if a != p}).most_common(5)
    ],
    "seconds": round(time.time() - t, 1),
}
print(json.dumps(loo, indent=1))

# 2) live augmented re-embedding
random.seed(11)
picks = random.sample(range(len(index.records)), 300)
hits, lat = 0, []
for i in picks:
    path = resolve_dataset_file(index.records[i].file_path, settings.waste_image_root_paths)
    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        aug = im.crop((int(w * .1), int(h * .1), int(w * .9), int(h * .9))).rotate(random.choice([-15, 10, 15]), expand=True)
        buf = io.BytesIO()
        aug.save(buf, "JPEG", quality=80)
    t = time.time()
    vec = index.embed(buf.getvalue())
    lat.append(time.time() - t)
    sims = V @ vec
    exclude = (V @ V[i]) >= DUP  # the source image and its duplicates
    pred, _ = vote(sims, exclude)
    hits += pred == cats[i]
lat_ms = sorted(x * 1000 for x in lat[1:])  # drop model-load call
aug = {
    "images": len(picks),
    "top1_agreement": round(hits / len(picks), 4),
    "embed_latency_ms_median": round(lat_ms[len(lat_ms) // 2], 1),
    "embed_latency_ms_p95": round(lat_ms[int(len(lat_ms) * .95)], 1),
    "device": "cuda" if __import__("torch").cuda.is_available() else "cpu",
}
print(json.dumps(aug, indent=1))
OUT.write_text(json.dumps({"leave_one_out": loo, "augmented_live": aug}, indent=1))
