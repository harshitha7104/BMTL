# ScrapTrust Copilot

A chat assistant for scrap, waste and mineral analysis. The LLM handles conversation and reasoning.
Its domain evidence comes from this project's own unsupervised models, which it calls as tools.

```
React  ──►  POST /api/v1/copilot/chat  ──►  CopilotService (sessions, attachments)
                                              │
                         ┌────────────────────┴────────────────────┐
                    LLM provider                              Domain tools
   claude · openai · gemini · openai_compatible · offline     analyze_waste_image      (DINOv2 kNN + K-Means)
                                                              assess_image_quality     (evidence-quality heuristics)
                                                              get_waste_cluster_profile / get_waste_dataset_overview
                                                              interpret_mineral_spectrum (mineral/ rule engine + PCA/K-Means)
                                                              get_mineral_model_info
```

## Why tools rather than fine-tuning

Current hosted models (Claude, GPT, Gemini) don't learn your data from a fine-tune in a way that
can be checked. Here the assistant is specialized by three things:

1. **A domain system prompt**: scrap grades, waste streams, hazards and spectroscopy, plus rules for treating evidence honestly
   ([app/copilot/prompts.py](../backend/app/copilot/prompts.py)).
2. **Tools backed by the unsupervised models.** Every claim about an uploaded photo or spectrum can be traced back to a
   tool output, and the UI shows each one under "Evidence".
3. **Vision**: Claude, GPT-4o and Gemini also look at the photo directly.

Retraining the embeddings or clusters (`backend/scripts/`) or the mineral model (`mineral/run_pipeline.py`) improves
the copilot right away, with no prompt changes.

## Chat experience

The web app opens on the Copilot. It has a sidebar (New chat, Chats, Assessments, and Recents grouped by date, each
deletable), a greeting with a centred message box when a chat is empty, and a thread view with the message box at the
bottom once a conversation starts. The message box has:

- **+ menu**: upload photos and videos, take a photo (camera on phones), upload audio, upload documents and spectra.
  Drag-and-drop and pasting images also work.
- **🎤 microphone**: records with the browser's MediaRecorder (live level meter, timer, cancel). The recording is
  sent to `POST /api/v1/copilot/transcribe`, transcribed locally with Whisper, and the text is inserted into the box
  for you to edit and send.
- **Model picker**: switch between configured providers.

Each answer shows a "Used N analysis tools" chip (expand it to see every tool input and output), copy, 👍/👎 and,
for photo answers, "Correct the category".

## Inputs

| Input | What happens |
|---|---|
| Photo (JPEG/PNG/WebP) | Evidence-quality check + DINOv2 dataset similarity; vision LLMs also see the image |
| Video (MP4/MOV/WebM...) | 4 evenly spaced frames are stored as `image_N` (marked "frame from video_N") and analysed like photos; the soundtrack is transcribed |
| Audio / voice note | Transcribed locally; with no typed text, the transcript is treated as the question |
| PDF / TXT / MD / non-spectral CSV | Text extracted (up to 20k characters) and passed to the model |
| Spectrum (CSV/XLSX with a 400–2500 nm wavelength column) | Mineral engine interpretation |

Whisper runs on the CPU (int8) by default, which is safe everywhere; set `WHISPER_MODEL` (tiny…large-v3),
`WHISPER_DEVICE=cuda` and `WHISPER_COMPUTE_TYPE=float16` for GPU use where cuDNN 9 is installed. Audio and video
uploads may be up to `COPILOT_MAX_MEDIA_MB` (200 MB).

## Scope

The Copilot answers questions about scrap, waste, recycling, batteries, hazardous materials, minerals and
spectroscopy, and about this project. It declines other questions politely:
- **With an LLM:** a scope rule in the system prompt (mixed questions get only the in-scope part answered).
- **Offline:** a domain classifier (unambiguous domain terms, then knowledge-base similarity that must share at
  least two content words) routes in-scope questions to the knowledge base and declines the rest.

## Knowledge base

`backend/app/copilot/knowledge/scrap_waste_minerals.md` holds curated reference notes, one `## ` entry per topic,
covering metal identification, scrap grades, battery and e-waste safety, recycling processes, hazards, sorting
technology, spectroscopy, mineral features and the project itself. LLMs reach it through the `search_knowledge_base`
tool, and offline mode answers from it directly. Add or edit entries in that file; no retraining is needed.

## Reviewer feedback → verified labels

Each answer has 👍/👎 and **Correct the category** controls. For answers about photos, each review appends one row
per image to `backend/data/copilot/reviewed_labels.jsonl`. Each row holds the image SHA-256, the model's predicted
category, the reviewer's verified category and a note.

- `POST /api/v1/copilot/sessions/{id}/feedback` `{turn_index, rating: up|down, corrected_category?, note?}`
- `GET /api/v1/copilot/feedback/summary`: counts and the model's agreement rate with reviewers
- `GET /api/v1/copilot/feedback/export`: all reviewed labels, ready to use as ground truth for re-clustering or a supervised head

## Running

The easiest way is to double-click `ScrapTrust.bat` in the repository root. It sets up on the first run and serves
everything on http://localhost:8010. To set up manually:

```bash
cd backend
pip install -r requirements.txt -r requirements-copilot.txt
# optional, for dataset similarity on NEW photos (DINOv2):
pip install -r requirements-phase-b.txt
cp .env.example .env    # set ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY or an OpenAI-compatible URL
uvicorn app.main:app --port 8000
```

Then run `npm run dev` from the repository root and open **Copilot** in the nav.

With no key configured, the `offline` provider still works. It runs the engines directly and renders a fixed report.

## Providers

| `COPILOT_PROVIDER` | Settings | Notes |
|---|---|---|
| `claude` | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` (default `claude-opus-5-5`), `ANTHROPIC_EFFORT` | Prompt caching on the system prompt; server-side refusal fallback enabled |
| `openai` | `OPENAI_API_KEY`, `OPENAI_MODEL` | Chat Completions function calling |
| `gemini` | `GEMINI_API_KEY`, `GEMINI_MODEL` | `google-genai` function calling |
| `openai_compatible` | `OPENAI_COMPATIBLE_BASE_URL`, `OPENAI_COMPATIBLE_MODEL`, `OPENAI_COMPATIBLE_API_KEY` | Ollama, LM Studio, vLLM, Groq, OpenRouter, ... (model must support tools; vision optional) |
| `offline` | none | No LLM |
| `auto` (default) | | First configured of claude → openai → gemini → openai_compatible, else offline |

The UI lets you switch between configured providers for each message.

## Data the tools read

- `data/embeddings/dinov2_vits14/` and `data/embeddings/clusters/` (git-ignored; produced by `backend/scripts/`).
- `mineral/` (model at `mineral/models/spectral_model.joblib`; scikit-learn must match `model_card.json`).
- Waste images: `data/raw/wastes/` or `wastes/` (`WASTE_IMAGE_ROOTS`). Only needed to open the original files.

## Limits to keep in mind

- Waste categories are unverified folder labels, and the K-Means silhouette is about 0.05. Similarity is evidence, not classification.
- The mineral engine has no ground truth. Its confidence measures how well the evidence agrees; it is not a probability.
- Alloy grade, chemistry and contamination need XRF/LIBS or lab analysis. The copilot is told to say so.
