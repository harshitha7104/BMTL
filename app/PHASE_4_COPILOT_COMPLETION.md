# Phase 4 Completion: ScrapTrust Copilot

## What was built

A chat assistant for scrap, waste and mineral analysis (the **Copilot** tab in the app, `/api/v1/copilot`).
The LLM handles conversation and reasoning. Domain evidence comes from this project's own unsupervised models,
which the LLM calls as tools:

| Tool | Engine |
|---|---|
| `analyze_waste_image` | DINOv2 ViT-S/14 embedding of the photo, compared against the 11,521-image index: nearest images, weighted category votes, agreement level, nearest K-Means cluster, novelty flag |
| `assess_image_quality` | Existing evidence-quality heuristics (resolution, blur, exposure) |
| `get_waste_cluster_profile`, `get_waste_dataset_overview` | Cluster and dataset statistics |
| `interpret_mineral_spectrum`, `get_mineral_model_info` | `mineral/` rule engine and PCA/K-Means spectral model (loaded unmodified) |

Providers: **Claude** (`claude-opus-5-5`, prompt caching, server-side refusal fallback), **OpenAI**, **Gemini**,
**any OpenAI-compatible endpoint** (Ollama, LM Studio, vLLM, Groq, OpenRouter) and an **offline** mode that needs no key.
`COPILOT_PROVIDER=auto` picks the first configured one, and the UI can switch providers for each message.

Specialization comes from a domain system prompt plus tool grounding, not fine-tuning; see [docs/copilot.md](docs/copilot.md).

**Shipping as one product:**
- **One-click start:** `ScrapTrust.bat` / `run_scraptrust.ps1` sets up on the first run, rebuilds the web app when sources change, and serves the web app, API and Copilot from a single server on port 8010 (or the next free port). It then opens the browser.
- **Reviewer loop:** 👍/👎 and "Correct the category" on every answer. Reviews of photo answers are appended to `reviewed_labels.jsonl` with the image hash, the model's prediction and the verified label, and can be exported through `/api/v1/copilot/feedback/export`. This is how the unverified dataset gains ground truth.

## Measured results

### Waste-image similarity ([data/evaluations/phase4/copilot_waste_knn_eval.json](data/evaluations/phase4/copilot_waste_knn_eval.json))

Agreement of the top-8 neighbour vote with the **unverified** folder category. Exact and near-duplicates
(cosine ≥ 0.995) of each query are excluded so duplicated files cannot inflate the score.

| Test | Images | Agreement |
|---|---|---|
| Leave-one-out over the full index | 11,521 | **92.3%** |
| Live GPU re-embedding of altered photos (crop + rotate + JPEG) | 300 | **90.0%** |

The copilot's agreement label tracks how reliable its answer is:

| Agreement label | Share of images | Agreement with folder category |
|---|---|---|
| strong (top share ≥ 75%) | 84.9% | **97.4%** |
| moderate (50–75%) | 12.0% | 68.7% |
| weak (< 50%) | 3.0% | 44.3% |

Per category: battery 95.8%, organic 95.6%, paper 94.7%, light bulbs 94.3%, automobile 93.1%, E-waste 92.2%,
glass 90.6%, plastic 90.3%, metal 87.6%. The most frequent confusions are metal → automobile (60),
glass → plastic (56) and paper → plastic (56).

**Embedding consistency:** six random dataset images re-embedded live match their stored vectors at cosine 1.0000.
**Latency** (Quadro T2000, CUDA 12.8): median 23 ms and p95 142 ms per photo, plus a one-time ~6 s model load.

### Mineral spectra
- The repository's synthetic Al-OH doublet test spectrum → "Al-OH clay/mica mineral group" (INFERRED, evidence confidence 0.308).
- A live API test with a separately generated Al-OH spectrum gave the same result in 34 ms.

### Tests
- Backend: **99 passed, 0 failed** (16 new copilot tests, including feedback; the two Phase 3 tests that previously failed for lack of torch/matplotlib now pass).
- Frontend: `tsc --noEmit` is clean and `vite build` succeeds.
- Launcher: run for real. It rebuilt the changed web app, picked port 8010 (8000 is used by another local project) and served the app, `/health` and the API from one process.
- Browser check on the launched product: dataset overview, spectrum upload, photo upload through the attach button (a synthetic image was correctly flagged "possibly out of distribution", weak agreement), category correction saved and exported, and the phone-width layout (375 px, no horizontal scroll).

## Setup changes
- `backend/requirements-copilot.txt` holds the LLM SDKs and the engine dependencies. The `pydantic` pin in `requirements.txt` was relaxed to `>=2.10.4,<3` because the current SDKs need a newer 2.x (tested with 2.14.3).
- `start_local.ps1` now installs the Copilot requirements and torch (CUDA wheels when an NVIDIA GPU is found). It is saved as UTF-8 with a BOM so Windows PowerShell 5.1 parses its ✓ characters, which the previous version failed to do.
- `backend/venv` is created with every dependency, and `backend/.env` is created from the template (both git-ignored).
- `.gitignore` now covers `venv/`, `.env`, `backend/data/` (runtime sessions) and the second local copy of the image dataset, `wastes/`.
- `mineral/` is now part of the repository as the spectral engine the Copilot calls.

## Limitations
- **No live LLM call has been made.** There is no Anthropic, OpenAI or Gemini key on this machine. The provider code is tested against fake SDK clients that mirror the installed SDK signatures (anthropic 2.8, openai 3.51, google-genai 3.3). Add a key to `backend/.env` to enable it.
- Agreement is measured against folder labels that nobody has verified. Leave-one-out still allows similar-looking images from the same source, so real-world accuracy on new yards will be lower.
- Visual similarity cannot give alloy grade or chemistry. The copilot is instructed to recommend XRF/LIBS or a lab assay.
- The mineral model has no ground truth. Its confidence measures how well the evidence agrees; it is not a probability.

## Re-running
```bash
cd backend
venv/Scripts/python -m pytest tests -q
venv/Scripts/python scripts/evaluate_copilot_waste_knn.py
```
