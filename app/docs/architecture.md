# Scrap Evidence Assessment & Trust Report System

## Architecture Overview

### System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT LAYER                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  Dashboard    │  │  Upload      │  │  Assessment Results  │  │
│  │  (Overview)   │  │  (Drag-Drop) │  │  & Trust Report     │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                  │                      │              │
│  ┌──────┴──────────────────┴──────────────────────┴───────────┐ │
│  │              Service Layer (API Client)                     │ │
│  │  • Assessment Service  • Image Quality Service              │ │
│  │  • Validation Service  • Error Handling                     │ │
│  └──────────────────────────┬──────────────────────────────────┘ │
└─────────────────────────────┼───────────────────────────────────┘
                              │ HTTPS
┌─────────────────────────────┼───────────────────────────────────┐
│                        API LAYER (FastAPI)                       │
│  ┌──────────────────────────┴──────────────────────────────────┐ │
│  │                    API Routes (v1)                           │ │
│  │  POST /assessments  GET /assessments/{id}                   │ │
│  │  POST /feedback     GET /report                             │ │
│  └──────────────────────────┬──────────────────────────────────┘ │
│                              │                                    │
│  ┌──────────────────────────┴──────────────────────────────────┐ │
│  │                  Service Layer                               │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │ │
│  │  │  Assessment   │  │   Image      │  │   OpenAI         │  │ │
│  │  │  Service      │  │   Quality    │  │   Service        │  │ │
│  │  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │ │
│  └─────────┼──────────────────┼───────────────────┼────────────┘ │
│            │                  │                   │              │
│  ┌─────────┴──────────────────┴───────────────────┴────────────┐ │
│  │                  Repository Layer                            │ │
│  │  (Abstract interface — swappable between local/PostgreSQL)   │ │
│  └──────────────────────────┬──────────────────────────────────┘ │
└─────────────────────────────┼───────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
        ┌─────┴─────┐  ┌─────┴─────┐  ┌─────┴─────┐
        │  Local FS  │  │ PostgreSQL│  │    S3     │
        │  (Dev)     │  │ (Prod)    │  │  (Prod)   │
        └───────────┘  └───────────┘  └───────────┘
```

### Data Flow: Image Upload → Trust Report

```
1. USER UPLOADS IMAGES
   │
   ├─→ Client-side validation (file type, size, format)
   ├─→ Client-side image quality pre-check (brightness, sharpness, contrast)
   ├─→ Compute file hash (SHA-256) for deduplication
   │
2. API RECEIVES UPLOAD
   │
   ├─→ Server-side validation (magic bytes, not just extension)
   ├─→ Safe filename generation (prevent path traversal)
   ├─→ Rate limiting check
   ├─→ Generate unique assessment_id
   ├─→ Store metadata (timestamp, file info, hash)
   │
3. IMAGE QUALITY ASSESSMENT
   │
   ├─→ Deep quality analysis (resolution, exposure, blur, obstruction)
   ├─→ Determine quality status: sufficient / partially_sufficient / insufficient
   ├─→ Identify specific issues and recommend additional photos
   ├─→ TERMINATE ONLY if truly unreadable/corrupted (score < 15)
   ├─→ For partially_sufficient: proceed with analysis, return quality warning,
   │   limited observations, unknown fields, and recommendations
   │
4. MULTIMODAL AI ANALYSIS (Provider-Independent Interface)
   │   Default: MockProvider (no API key needed)
   │   Optional: OpenAI Responses API with Structured Outputs
   │   Model configurable via OPENAI_MODEL env var (never hardcoded)
   │
   ├─→ Structured system prompt enforcing:
   │   ├─ Separation of observations/inferences/unknowns
   │   ├─ Confidence levels for each inference
   │   ├─ Explicit identification of limitations
   │   ├─ No hallucination of chemical composition
   │   └─ Recommendation of physical tests
   │
   ├─→ Structured JSON response (validated against Pydantic schema)
   ├─→ Retry logic for transient failures
   ├─→ Timeout handling
   ├─→ Graceful degradation for malformed responses
   │
5. ASSESSMENT ASSEMBLY
   │
   ├─→ Combine quality assessment + AI analysis
   ├─→ Apply trust/safety rules:
   │   ├─ Never claim exact composition from appearance
   │   ├─ Flag uncertain assessments for human review
   │   ├─ Include all caveats and limitations
   │   └─ Separate AI output from verified corrections
   │
   ├─→ Store complete assessment record
   │
6. TRUST REPORT GENERATION
   │
   ├─→ Present findings with clear visual separation:
   │   ├─ OBSERVED (blue) — directly visible
   │   ├─ INFERRED (amber) — tentative, with confidence
   │   ├─ UNKNOWN (red) — cannot be determined
   │   └─ VERIFIED (green) — confirmed by human expert
   │
   ├─→ Include limitations disclaimer
   ├─→ Include recommended next steps
   └─→ Provide assessment_id for traceability
```

## Security Architecture

### Threat Model & Mitigations

| Threat | Risk | Mitigation |
|--------|------|------------|
| Malicious file upload | High | Magic byte validation, not just extension; size limits; type whitelist |
| Path traversal | High | Safe filename generation; no user-controlled paths |
| API key exposure | Critical | Environment variables only; never in client code or logs |
| Prompt injection | Medium | Structured output validation; system prompt hardening |
| Rate abuse | Medium | Rate limiting per IP; upload size limits |
| Data leakage | High | No internal paths in responses; sanitized error messages |
| AI hallucination | High | Schema validation; explicit uncertainty; human review flags |
| Unauthorized access | Medium | Assessment IDs are non-guessable UUIDs |

### Trust & Safety Rules (Enforced)

1. **Never claim exact chemical composition** from visual appearance alone
2. **Never claim exact alloy grade** without spectroscopic verification
3. **Never provide definitive pricing** based only on images
4. **Never state that images confirm purity or weight**
5. **Explicitly identify all unknown information**
6. **Use qualitative human review triggers** — NOT numeric confidence thresholds:
   - `insufficient_evidence` — Image quality too poor
   - `high_uncertainty` — Multiple conflicting inferences
   - `conflicting_images` — Uploaded images contradict each other
   - `consequential_claim` — Grade/composition claimed without verification
   - `unsupported_conclusion` — Inference lacks adequate visual evidence
   - `hazardous_material` — Potential safety risk identified
   - `mixed_material` — Cannot separate components visually
   - `electronic_scrap` — Requires specialized e-waste handling
   - `low_quality_images` — Image quality below analysis threshold
   - `model_refusal` — AI model refused to analyze (safety/policy)
   - `schema_validation_failure` — AI response didn't match expected schema
   - `processing_error` — Technical error during analysis
7. **Keep AI output separate** from verified human corrections (immutable AI output + separate FeedbackRecord)
8. **Do not auto-retrain** using unverified predictions
9. **Store feedback separately** from original AI output
10. **Never expose API keys**, credentials, or internal errors
11. **Validate all user input** with strict schemas
12. **Do not trust file extensions** — verify magic bytes
13. **Rate limiting** on all endpoints
14. **Safe filenames** — prevent path traversal attacks
15. **All AI reports include** appropriate limitations

### Provider-Independent AI Interface

The system uses an abstract `IAIProvider` interface so that:
- **MockProvider** (default) — works without any API key or budget
- **OpenAIProvider** (optional) — uses Responses API with Structured Outputs, configurable via `OPENAI_MODEL` env var
- **LocalVisionProvider** (optional) — requires hardware verification before use

Key constraints:
- No paid API calls during development or testing
- Model is NEVER hardcoded — always from environment configuration
- OpenAI integration is OPTIONAL, not required
- No large local model downloads without hardware check

## Technology Stack

### Frontend (This Demo)
- **React 18** with TypeScript
- **Tailwind CSS** for styling
- **Vite** for build tooling
- **Lucide React** for icons
- **UUID** for unique identifiers

### Backend (Production — Not Included in Demo)
- **Python 3.11+**
- **FastAPI** — async REST API framework
- **Pydantic v2** — schema validation
- **OpenAI SDK** — multimodal image analysis
- **Uvicorn** — ASGI server
- **PostgreSQL** — production data storage
- **S3-compatible** — image object storage

## API Endpoints (Production Backend)

```
GET  /health                              — System health check
POST /api/v1/assessments                  — Create new assessment (upload images)
GET  /api/v1/assessments/{id}             — Get assessment by ID
POST /api/v1/assessments/{id}/feedback    — Submit human review feedback
GET  /api/v1/assessments/{id}/report      — Get formatted trust report
```

## Assessment Schema

Every assessment contains:

```typescript
{
  assessment_id: string;           // Unique identifier (ASM-XXXXXXXX)
  evidence_quality: {
    status: 'sufficient' | 'partially_sufficient' | 'insufficient';
    issues: QualityIssue[];
    recommended_additional_photos: string[];
    human_review_required: boolean;
    overall_score: number;         // 0-100
  };
  visual_observations: Observation[];  // Directly visible characteristics
  observed: Observation[];             // Same as visual_observations
  inferred: Inference[];               // Tentative interpretations
  unknown: Unknown[];                  // Cannot be determined
  proposed_assessment: {
    material_family: MaterialFamily;
    scrap_form: ScrapForm;
    surface_condition: SurfaceCondition;
    visible_contamination: VisibleContamination;
    description: string;
    caveats: string[];
  };
  confidence: number;              // 0.0 - 1.0
  missing_evidence: string[];
  recommended_next_steps: string[];
  human_review_required: boolean;
  scanner_xrf_recommended: boolean;
  processing_metadata: {
    model_used: string;
    processing_time_ms: number;
    tokens_used: number;
    image_count: number;
  };
  status: AssessmentStatus;
  created_at: string;
}
```

## Known Limitations (MVP)

1. **No real AI analysis** — This demo uses simulated responses
2. **No persistent storage** — Data is lost on page refresh
3. **No authentication** — No user accounts or access control
4. **No real backend** — All processing is client-side simulation
5. **Limited image analysis** — Client-side quality checks only

## Production Extension Plan

### Phase 1: Backend Implementation
- FastAPI with Pydantic schemas
- OpenAI GPT-4o multimodal integration
- Local file storage with abstract repository pattern

### Phase 2: Production Storage
- PostgreSQL for assessment records
- S3-compatible object storage for images
- Redis for rate limiting and caching

### Phase 3: Authentication & Authorization
- JWT-based authentication
- Role-based access control
- Audit logging

### Phase 4: Advanced Features
- Batch assessment processing
- Historical trend analysis
- Custom assessment templates
- Integration with XRF scanner data
- Mobile app for field capture

### Phase 5: ML Enhancement
- Fine-tuned material classification model
- Ensemble confidence scoring
- Anomaly detection for unusual materials
- Feedback loop for continuous improvement

## Running This Demo

```bash
# Development
npm run dev

# Production build
npm run build

# Type checking
npm run typecheck
```

## Environment Variables (Production Backend)

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
MAX_UPLOAD_SIZE_MB=10
ALLOWED_IMAGE_TYPES=image/jpeg,image/png,image/webp
MAX_IMAGES_PER_ASSESSMENT=5
DATABASE_URL=postgresql://...
S3_BUCKET=scrap-assessments
S3_ENDPOINT=https://...
RATE_LIMIT_PER_MINUTE=30
LOG_LEVEL=INFO
```
