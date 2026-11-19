# API Documentation

## Base URL

```
Production: https://api.scraptrust.example.com/api/v1
Development: http://localhost:8000/api/v1
```

## Authentication

```
# Future: JWT Bearer Token
Authorization: Bearer <token>

# MVP: No authentication (rate-limited by IP)
```

## Endpoints

---

### GET /health

System health check.

**Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

---

### POST /api/v1/assessments

Create a new assessment by uploading scrap material images.

**Request:**
- Content-Type: `multipart/form-data`
- Body: `images` (array of image files, max 5)

**Validation Rules:**
- Accepted formats: JPEG, PNG, WebP
- Maximum file size: 10MB per image
- Maximum images: 5 per request
- File type verified by magic bytes (not just extension)
- Corrupted files rejected

**Response (202 Accepted):**
```json
{
  "success": true,
  "data": {
    "assessment_id": "ASM-A1B2C3D4",
    "status": "processing",
    "created_at": "2024-01-15T10:30:00Z",
    "message": "Assessment created. Processing will complete shortly."
  }
}
```

**Error Responses:**
```json
// 400 Bad Request — Invalid file type
{
  "success": false,
  "error": "VALIDATION_ERROR",
  "message": "File type 'application/pdf' is not supported. Accepted: image/jpeg, image/png, image/webp"
}

// 413 Payload Too Large — File exceeds size limit
{
  "success": false,
  "error": "FILE_TOO_LARGE",
  "message": "File 'image.jpg' (15.2MB) exceeds maximum size of 10MB"
}

// 429 Too Many Requests — Rate limit exceeded
{
  "success": false,
  "error": "RATE_LIMIT_EXCEEDED",
  "message": "Maximum 30 requests per minute. Try again later."
}
```

---

### GET /api/v1/assessments/{assessment_id}

Retrieve a completed assessment.

**Path Parameters:**
- `assessment_id` (string) — The unique assessment identifier

**Response (200 OK):**
```json
{
  "success": true,
  "data": {
    "assessment_id": "ASM-A1B2C3D4",
    "evidence_quality": {
      "status": "partially_sufficient",
      "issues": [
        {
          "issue": "moderate_blur",
          "severity": "medium",
          "description": "Image shows moderate blur affecting fine detail visibility"
        }
      ],
      "recommended_additional_photos": [
        "Take photo in brighter, even lighting",
        "Include a ruler or coin for scale reference"
      ],
      "human_review_required": false,
      "overall_score": 65
    },
    "material_family": "ferrous",
    "scrap_form": "irregular",
    "visible_surface_condition": "heavily_rusted",
    "visible_contamination": "dirt_soil",
    "visual_observations": [
      {
        "finding": "Dark brown-orange surface discoloration consistent with iron oxide",
        "supporting_evidence": "Uniform rust coloring across 80% of visible surface",
        "category": "surface"
      }
    ],
    "observed": [...],
    "inferred": [
      {
        "finding": "Material is likely a ferrous alloy",
        "confidence": 0.72,
        "supporting_visual_evidence": "Rust pattern characteristic of iron oxidation",
        "limitations": "Cannot distinguish carbon steel from cast iron visually",
        "category": "material_family"
      }
    ],
    "unknown": [
      {
        "item": "Exact alloy composition",
        "reason": "Cannot be determined from visual inspection",
        "required_evidence": "XRF spectroscopy or laboratory analysis"
      }
    ],
    "proposed_assessment": {
      "material_family": "ferrous",
      "scrap_form": "irregular",
      "surface_condition": "heavily_rusted",
      "visible_contamination": "dirt_soil",
      "description": "Ferrous scrap with heavy surface oxidation...",
      "estimated_grade_hint": "Possibly carbon steel (unverified)",
      "grade_hint_confidence": 0.35,
      "caveats": [
        "Material grade cannot be confirmed without spectroscopic analysis",
        "Surface rust may significantly reduce visible metal recovery"
      ]
    },
    "confidence": 0.72,
    "missing_evidence": [
      "Close-up photograph of material cross-section",
      "Photograph with scale reference"
    ],
    "recommended_next_steps": [
      "Perform XRF analysis to determine alloy composition",
      "Conduct physical inspection for internal corrosion"
    ],
    "human_review_required": false,
    "scanner_xrf_recommended": true,
    "processing_metadata": {
      "model_used": "gpt-4o",
      "processing_time_ms": 3200,
      "tokens_used": 2450,
      "image_count": 2,
      "total_image_size_bytes": 4500000,
      "validation_passed": true,
      "retry_count": 0
    },
    "status": "completed",
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-01-15T10:30:05Z"
  }
}
```

**Error Responses:**
```json
// 404 Not Found
{
  "success": false,
  "error": "NOT_FOUND",
  "message": "Assessment 'ASM-INVALID' not found"
}
```

---

### POST /api/v1/assessments/{assessment_id}/feedback

Submit human expert feedback for an assessment.

**Request Body:**
```json
{
  "reviewer_name": "John Smith",
  "corrections": {
    "material_family": "ferrous",
    "scrap_form": "bar",
    "surface_condition": "lightly_rusted",
    "additional_notes": "Material is actually mild steel bar, not irregular scrap"
  },
  "confidence_override": 0.85,
  "verified": true
}
```

**Response (200 OK):**
```json
{
  "success": true,
  "data": {
    "message": "Feedback recorded successfully",
    "feedback_id": "FB-X1Y2Z3",
    "assessment_updated": true
  }
}
```

**Important:** Feedback is stored separately from the original AI output. The original assessment is preserved for audit purposes.

---

### GET /api/v1/assessments/{assessment_id}/report

Get a formatted trust report for an assessment.

**Response (200 OK):**
```json
{
  "success": true,
  "data": {
    "report_id": "RPT-A1B2C3D4",
    "assessment_id": "ASM-A1B2C3D4",
    "generated_at": "2024-01-15T10:35:00Z",
    "format": "json",
    "content": {
      "summary": "...",
      "evidence_section": {...},
      "findings_section": {...},
      "limitations_section": {...},
      "recommendations_section": {...}
    },
    "verification_status": "unverified",
    "human_reviewed": false
  }
}
```

---

## Error Response Format

All errors follow a consistent format:

```json
{
  "success": false,
  "error": "ERROR_CODE",
  "message": "Human-readable error description",
  "details": {} // Optional additional context
}
```

### Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| VALIDATION_ERROR | 400 | Request validation failed |
| FILE_TOO_LARGE | 413 | Upload exceeds size limit |
| UNSUPPORTED_FORMAT | 400 | File type not accepted |
| CORRUPTED_FILE | 400 | File appears corrupted |
| RATE_LIMIT_EXCEEDED | 429 | Too many requests |
| NOT_FOUND | 404 | Resource not found |
| PROCESSING_ERROR | 500 | Internal processing failure |
| AI_SERVICE_ERROR | 502 | AI model service unavailable |
| TIMEOUT | 504 | Request timed out |

---

## Rate Limiting

| Endpoint | Limit | Window |
|----------|-------|--------|
| POST /assessments | 30 | per minute |
| GET /assessments/{id} | 120 | per minute |
| POST /feedback | 10 | per minute |

Rate limit headers are included in all responses:
```
X-RateLimit-Limit: 30
X-RateLimit-Remaining: 28
X-RateLimit-Reset: 1705312260
```
