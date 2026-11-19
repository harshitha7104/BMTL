# ScrapTrust Backend

FastAPI-based backend for scrap material evidence assessment.

## Features

- **Provider-Independent AI Interface**: Works with mock, OpenAI, or local vision models
- **No API Key Required**: Mock provider works out of the box for development
- **Structured Assessment Output**: Clear separation of observations, inferences, and unknowns
- **Qualitative Review Triggers**: Human review based on evidence quality, not numeric thresholds
- **Immutable AI Output**: Feedback stored separately from original assessment
- **Safe Image Handling**: Magic byte validation, size limits, corruption detection

## Quick Start

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env

# Run development server
uvicorn app.main:app --reload --port 8000

# Open API documentation
# http://localhost:8000/docs
```

## Running Tests

```bash
# Install test dependencies (included in requirements.txt)
pip install pytest pytest-asyncio httpx

# Run tests
pytest tests/ -v
```

## API Endpoints

### Health Check
```
GET /health
```

### Create Assessment
```
POST /api/v1/assessments
Content-Type: multipart/form-data

Body: images (file array, max 5)
```

### Get Assessment
```
GET /api/v1/assessments/{assessment_id}
```

### List Assessments
```
GET /api/v1/assessments?skip=0&limit=20
```

### Submit Feedback
```
POST /api/v1/assessments/{assessment_id}/feedback
Content-Type: application/json

Body: {
  "reviewer_name": "John Doe",
  "corrections": {
    "material_family": "ferrous",
    "additional_notes": "Actually mild steel"
  },
  "verified": false
}
```

### Get Feedback
```
GET /api/v1/assessments/{assessment_id}/feedback
```

## Configuration

Edit `.env` to configure:

- `AI_PROVIDER`: "mock" | "openai" | "local" (default: "mock")
- `OPENAI_API_KEY`: Required only if AI_PROVIDER="openai"
- `OPENAI_MODEL`: Model name (default: "gpt-4o")
- `MAX_UPLOAD_SIZE_MB`: Max image size (default: 10)
- `MAX_IMAGES_PER_ASSESSMENT`: Max images per request (default: 5)
- `LOCAL_STORAGE_PATH`: Storage directory (default: "./data")

## Architecture

```
backend/
├── app/
│   ├── main.py                 # FastAPI entry point
│   ├── core/
│   │   ├── config.py           # Environment configuration
│   │   └── exceptions.py       # Custom exceptions
│   ├── api/
│   │   ├── deps.py             # Dependency injection
│   │   └── routes/
│   │       ├── health.py       # Health check
│   │       ├── assessments.py  # Assessment CRUD
│   │       └── feedback.py     # Feedback submission
│   ├── schemas/
│   │   └── assessment.py       # Pydantic models
│   ├── services/
│   │   ├── assessment_service.py      # Orchestration
│   │   └── image_quality_service.py   # Quality assessment
│   ├── providers/
│   │   ├── base.py             # AI provider interface
│   │   ├── mock_provider.py    # Mock implementation
│   │   └── registry.py         # Provider management
│   ├── repositories/
│   │   ├── base.py             # Repository interface
│   │   └── local_repository.py # JSON file storage
│   └── utils/
│       └── image_utils.py      # Image validation
└── tests/                      # Test suite
```

## AI Providers

### Mock Provider (Default)
- No API key required
- Returns realistic sample data
- Exercises all schema fields
- Suitable for development and testing

### OpenAI Provider (Optional)
- Requires `OPENAI_API_KEY`
- Uses GPT-4o or configured model
- Structured Outputs with Pydantic validation

### Local Provider (Future)
- Requires local model files
- Hardware requirements must be met
- Not yet implemented

## Trust & Safety

The system enforces strict rules:

1. **Never claims exact chemical composition** from appearance
2. **Never claims specific alloy grade** without verification
3. **Never provides pricing** based only on images
4. **Separates observations from inferences from unknowns**
5. **Uses qualitative review triggers**, not numeric thresholds
6. **Keeps AI output immutable** — feedback stored separately
7. **Validates all AI responses** against Pydantic schema

## Limitations

- Local JSON storage is for development only
- No authentication/authorization in MVP
- Mock provider returns sample data, not real analysis
- OpenAI integration requires API key and budget
- Local vision model not yet implemented

## Next Steps

- [ ] Add authentication (JWT)
- [ ] Implement PostgreSQL repository
- [ ] Add S3 storage for images
- [ ] Implement local vision model provider
- [ ] Add rate limiting middleware
- [ ] Implement dataset integration (separate workstream)
