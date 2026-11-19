"""Evaluate zero-shot material identification against the waste dataset folders.

Samples N images per source category from the test split, maps the predicted material to its dataset
category (copper/brass/steel/... -> "metal waste", lithium/lead-acid -> "battery waste", ...) and reports
agreement with the folder label, per category, by confidence level, plus which metals are named inside
"metal waste". Folder labels are unverified, so this measures agreement, not true accuracy.

Run from backend/:  python scripts/evaluate_material_identifier.py [per_category]
Writes data/evaluations/phase4/material_identifier_eval.json
"""
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.copilot.engines.material import MaterialIdentifier  # noqa: E402
from app.core.config import settings  # noqa: E402

PER_CAT = int(sys.argv[1]) if len(sys.argv) > 1 else 50
OUT = Path(__file__).resolve().parents[2] / "data" / "evaluations" / "phase4" / "material_identifier_eval.json"

root = next(r for r in settings.waste_image_root_paths if (r / "test").exists())
random.seed(5)
identifier = MaterialIdentifier()

hits, total = 0, 0
per_cat = defaultdict(lambda: [0, 0])
by_conf = defaultdict(lambda: [0, 0])
metal_names = Counter()
confusions = Counter()
start = time.time()
for cat_dir in sorted(p for p in (root / "test").iterdir() if p.is_dir()):
    files = sorted(f for f in cat_dir.iterdir() if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    for f in random.sample(files, min(PER_CAT, len(files))):
        r = identifier.identify(f.read_bytes(), top_k=1)
        if r.get("status") != "ok":
            continue
        pred = r["top_matches"][0]["dataset_category"]
        ok = pred == cat_dir.name
        hits += ok
        total += 1
        per_cat[cat_dir.name][0] += ok
        per_cat[cat_dir.name][1] += 1
        by_conf[r["confidence"]][0] += ok
        by_conf[r["confidence"]][1] += 1
        if cat_dir.name == "metal waste":
            metal_names[r["most_likely"]] += 1
        if not ok:
            confusions[(cat_dir.name, r["most_likely"])] += 1

result = {
    "images": total,
    "agreement_with_folder_category": round(hits / total, 4),
    "per_category": {c: round(h / n, 3) for c, (h, n) in sorted(per_cat.items())},
    "by_confidence": {c: {"images": n, "agreement": round(h / n, 3)} for c, (h, n) in by_conf.items()},
    "materials_named_in_metal_waste": dict(metal_names.most_common()),
    "top_confusions": [{"folder": a, "named": b, "count": n} for (a, b), n in confusions.most_common(8)],
    "model": identifier.model_id,
    "seconds": round(time.time() - start, 1),
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(result, indent=1), encoding="utf-8")
print(json.dumps(result, indent=1))
