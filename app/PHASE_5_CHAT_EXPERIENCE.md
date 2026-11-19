# Phase 5 Completion: Chat Experience, Voice & Media

## What was built

- **Claude-style chat app, branded for ACE Green Recycling.** The web app now opens on the Copilot:
  - a collapsible sidebar (New chat, Chats, Assessments, and Recents grouped by date with delete);
  - a greeting with a centred message box and suggestion pills on an empty chat;
  - a centred thread with user bubbles and assistant answers;
  - a "Used N analysis tools" evidence chip, copy and 👍/👎 on each answer;
  - a drawer on phones.

  The theme comes from acegreenrecycling.com: cream `#F6EFE8`, charcoal `#272525`, terracotta `#A3563A`, plus mint, green, amber and slate, with gothic sans type. The legacy screens (dashboard, assessments, trust report) were re-themed by remapping Tailwind's palette.

- **+ menu for any external input:**
  - photos and videos, camera capture, audio, documents and spectra;
  - drag-and-drop and paste;
  - previews (image thumbnails, video and audio players, file cards).

- **Microphone dictation:** MediaRecorder recording with a live level meter, timer and cancel. The recording goes to `POST /api/v1/copilot/transcribe` and is transcribed locally with faster-whisper (CPU int8 by default), and the text lands in the message box.

- **Media intake:**
  - audio files are transcribed, and the transcript is treated as the question when nothing is typed;
  - videos are reduced to 4 key frames, analysed like photos, and their soundtrack is transcribed;
  - text is extracted from PDF and text files;
  - CSVs are routed automatically to spectra or documents.

- **Topic scope:** the assistant answers questions about scrap, waste, recycling, batteries, hazards, minerals and the project, and declines anything else:
  - with an LLM, through the prompt's scope rule;
  - offline, through a domain classifier.

- **Knowledge base:** 40 curated reference entries, used by LLMs through a `search_knowledge_base` tool and answered directly in offline mode.

- **Conversation history API:** `GET/DELETE /api/v1/copilot/sessions[/{id}]`, plus `GET /sessions/{id}/attachments/{att}` for previews in reopened chats.

## Verified

| Check | Result |
|---|---|
| Backend tests | **106 passed** (7 new: off-topic refusal, small talk, knowledge answers, voice message, video frames + soundtrack, documents/CSV routing, sessions/attachments/dictation) |
| Frontend | `tsc` clean, production build OK |
| Local Whisper on three spoken questions (Windows TTS) | Word-for-word transcripts in 1–3 s each on CPU |
| Microphone in the real UI | Simulated mic stream → recording UI → stop → server transcription → text in composer (exact sentence) → sent → grounded lithium-battery answer |
| Off-topic | "Who won the football World Cup in 2018?" and a spoken "What is the capital city of France?" were both declined |
| Video in the real UI | MP4 of four metal-waste photos with narration → 4 frames analysed (8 tool calls; the last frame was metal waste 79%, strong agreement) and the narration transcribed exactly |
| History | New chat → reopen from Recents restored messages, audio player, video, 4 frame thumbnails and tool chips |
| Layout | Desktop 1280 px with sidebar; phone 375 px with drawer and no horizontal scroll |

Test media and test conversations were removed after verification.

## Issues found and fixed along the way
- faster-whisper 1.2.1 passes `metadata_errors` to `av.open`, which PyAV 19 removed. Audio is now decoded directly with PyAV to 16 kHz mono and passed to Whisper as an array.
- Short clips lost their last sampled frame. Frame sampling now uses the start of each segment.
- Offline scope check: everyday words such as "lead" or "glass" made "Who will lead the team?" look in scope. The classifier now needs unambiguous terms, or knowledge-base matches sharing at least two content words.

## Limits
- Still no live LLM call; this machine has no API key. Offline answers come from the knowledge base and tools.
- Offline scope detection errs toward declining borderline questions (for example "Is lead dangerous to handle?"). An LLM provider handles these properly.
- Whisper "base" is accurate for clear speech. Use `WHISPER_MODEL=small` or larger for noisy yards and accents.
- The layout follows common chat-app patterns (sidebar, centred composer). It uses ACE Green branding, not Anthropic's name or logo.

## Update: material identification (copper was not being named)

**Problem:** a photo of copper sheet offcuts was reported only as "metal waste 61% / glass 39%". The waste dataset has
no copper category (just nine broad folders), and offline mode had no way to name a material from its appearance.

**Fix:** a new `identify_material` tool (`backend/app/copilot/engines/material.py`):
- **Zero-shot CLIP** (`openai/clip-vit-base-patch16`): the photo is compared with several text descriptions of each
  of 21 materials, with no training involved.
- **Colour check**: the share of the item (background removed) that is copper-, brass- or grey-metal-coloured.
- **Guidance** for each material.
- **Offline answers** now lead with "Most likely material: …" and show dataset similarity as supporting evidence.
- **LLM providers** are told to call the tool for every photo.

**Results:**
- The copper photo is named **Copper, 99%, high confidence**; 84% of the item is copper-coloured.
- On 450 dataset test photos the named material agrees with the folder category **74%** of the time, rising to
  **86%** at high confidence. Within "metal waste" it names steel, rusty steel, copper, aluminium, lead and brass
  for different photos, not just one answer.
  (`backend/scripts/evaluate_material_identifier.py` → `data/evaluations/phase4/material_identifier_eval.json`)
- The models now warm up in the background at server start and load from the local cache with no network, so a
  photo is answered in about 1 s instead of a first-request wait of about 60 s.
