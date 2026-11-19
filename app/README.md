# ScrapTrust: Scrap, Waste & Mineral Copilot

An AI assistant for recyclers, scrap yards, waste operators and geologists. It works like ChatGPT, Claude or Gemini,
but its answers come from **your own unsupervised models**: an index of 11,521 waste images and a mineral
spectral engine. Every claim can be traced to a tool result.

- **A familiar chat app**: a sidebar with conversation history, a greeting with a centred message box, and a **+** button for attachments, all in ACE Green's colours.
- **Ask anything in the domain** (scrap grades, waste sorting, battery and e-waste safety, recycling processes, minerals, the project itself). It politely declines unrelated questions.
- **Speak instead of typing**: the 🎤 button records your voice and transcribes it **locally** with Whisper, so audio never leaves the machine.
- **Attach any evidence with +**:
  - **Photos**: the material is named (copper, brass, aluminium, steel, stainless, lead, batteries, e-waste… using zero-shot CLIP plus a colour check), matched against the waste dataset (DINOv2 + K-Means), checked for evidence quality, and seen by the LLM.
  - **Videos**: four key frames are analysed like photos and the soundtrack is transcribed.
  - **Audio and voice notes**: transcribed, and the transcript is treated as your question.
  - **PDF and text documents**: read in.
  - **Spectra** (VNIR–SWIR CSV/XLSX): absorption features, mineral hypotheses and similar reference spectra.
- **Review answers** with 👍/👎 and category corrections. These become human-verified labels for retraining.
- **Formal assessments**: structured photo assessments with observed / inferred / unknown separation and a printable trust report.

## Start

**Double-click `ScrapTrust.bat`** (or run `.\run_scraptrust.ps1`).

The first run sets everything up (Python environment, dependencies, torch, web build). After that the launcher
starts one local server on **http://localhost:8010** (or the next free port) and opens your browser.

Requirements: Windows, Python 3.11+ and Node.js 18+. An NVIDIA GPU is optional; it makes photo matching faster.

### Turn on the full AI
Without a key the Copilot runs in **offline mode**, which runs the analysis engines but has no conversational LLM.
To enable an LLM, add one line to `backend/.env` and restart:

```ini
ANTHROPIC_API_KEY=sk-ant-...        # Claude (default: claude-opus-5-5)
# or OPENAI_API_KEY=sk-...          # OpenAI
# or GEMINI_API_KEY=...             # Google Gemini
# or OPENAI_COMPATIBLE_BASE_URL=http://localhost:11434/v1  +  OPENAI_COMPATIBLE_MODEL=...   # Ollama, Groq, OpenRouter...
```

`COPILOT_PROVIDER=auto` uses the first one configured. The chat header lets you switch providers for each message.

## Measured results

| | Result |
|---|---|
| Photo neighbour vote agrees with the dataset category (11,521 images, duplicates excluded) | **92.3%** |
| Same on 300 altered photos (crop, rotate, re-compress), embedded live | **90.0%** |
| Accuracy when the Copilot reports **strong** agreement (85% of photos) | **97.4%** |
| Accuracy when it reports moderate / weak agreement | 68.7% / 44.3% |
| Photo matching latency (Quadro T2000 GPU) | median 23 ms |
| Material identification agrees with the dataset folder (450 test photos, no training) | **74%**, or **86%** at high confidence |
| Copper sheet offcuts photo | named **Copper**, 99%, high confidence |
| Local speech-to-text on spoken test questions (Whisper base, CPU) | word-for-word, 1–3 s each |
| Backend test suite | 110 passed |

The dataset categories are folder labels that nobody has verified, so real-world accuracy on new yards will be lower.
The review buttons exist to build verified labels. Full details: [PHASE_4_COPILOT_COMPLETION.md](PHASE_4_COPILOT_COMPLETION.md).

## How it works

```
Browser ─► FastAPI (one server, also serves the web app)
              ├─ /api/v1/copilot      chat, sessions, feedback ─► LLM provider (Claude | OpenAI | Gemini | OpenAI-compatible | offline)
              │                                                     └─ calls tools:
              │                                                          analyze_waste_image        DINOv2 kNN + K-Means (data/embeddings)
              │                                                          assess_image_quality       evidence-quality heuristics
              │                                                          get_waste_cluster_profile / get_waste_dataset_overview
              │                                                          interpret_mineral_spectrum mineral/ rule engine + PCA/K-Means
              │                                                          get_mineral_model_info
              │                                                          search_knowledge_base      curated domain reference notes
              ├─ media intake          local Whisper speech-to-text, video frames + soundtrack, PDF/text extraction
              └─ /api/v1/assessments  formal photo assessments + trust reports
```

The assistant is specialized by a domain system prompt plus these tools, not by fine-tuning, so its answers stay
grounded in models you can inspect and retrain. See [docs/copilot.md](docs/copilot.md).

## Trust & safety rules

| Rule | How |
|---|---|
| No exact composition or alloy grade from images | Prompt rules; the Copilot recommends XRF/LIBS or a lab assay |
| No prices quoted as fact | Prompt rule; it may explain what drives price |
| Stays on topic | Off-topic questions (trivia, coding, news...) are declined: a scope rule in the LLM prompt, and a domain classifier in offline mode |
| Uncertainty is stated | Agreement level, novelty flag and evidence-quality score are returned with every photo analysis |
| Hazards are flagged | Batteries, mercury, CRT glass, refrigerants, PCBs, asbestos, oils |
| Source labels are not treated as ground truth | Caveats attached to every tool result; human reviews are stored separately |
| No secrets exposed | Keys only in `backend/.env` (git-ignored), hidden from settings output and the API |

## Project layout

```
ScrapTrust.bat / run_scraptrust.ps1   one-click launcher
backend/
  app/copilot/                        Copilot: providers, tools, engines, prompt, sessions
  app/api/routes/                     REST API (copilot, assessments, feedback, health)
  scripts/                            dataset audit, embedding, clustering, Copilot evaluation
  tests/                              99 tests
src/                                  React web app (Copilot, dashboard, assessments, trust report)
mineral/                              spectral interpretation engine and model
data/embeddings/                      DINOv2 vectors + K-Means clusters (generated, git-ignored)
data/evaluations/                     Phase 3 data audit, Phase 4 Copilot evaluation
docs/                                 copilot.md, architecture, API, assessment methodology
```

## Development

```bash
cd backend && venv/Scripts/python -m pytest tests -q        # backend tests
venv/Scripts/python scripts/evaluate_copilot_waste_knn.py   # re-measure photo matching
cd .. && npm run dev                                        # web app with hot reload (expects API on :8000)
npm run typecheck && npm run build
```

Reviewed labels: `GET /api/v1/copilot/feedback/export` (stored in `backend/data/copilot/reviewed_labels.jsonl`).
API docs: `/docs` on the running server.

## Limitations

- The waste categories are unverified folder labels, and the K-Means clusters separate them weakly (silhouette ≈ 0.05).
- The mineral model has no ground truth. Its confidence measures how well the evidence agrees; it is not a probability.
- There are no user accounts or authentication. It is designed to run locally.

## License

Proprietary. All rights reserved.
