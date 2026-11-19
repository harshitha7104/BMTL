# Backend Reference Implementation

This directory contains reference code for the production Python/FastAPI backend.
These files demonstrate the architecture and can be used as a starting point for
the full backend implementation.

## Quick Start (Production Backend)

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env
# Edit .env with your OpenAI API key

# Run development server
uvicorn app.main:app --reload --port 8000

# Run tests
pytest tests/ -v
```

## File Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI application entry point
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── health.py       # GET /health
│   │   │   ├── assessments.py  # CRUD assessment endpoints
│   │   │   └── feedback.py     # Feedback submission
│   │   └── deps.py             # Dependency injection
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── assessment.py       # Pydantic models
│   │   ├── evidence.py         # Evidence quality models
│   │   └── common.py           # Shared response schemas
│   ├── services/
│   │   ├── __init__.py
│   │   ├── assessment_service.py    # Business logic
│   │   ├── image_quality_service.py # Quality analysis
│   │   ├── openai_service.py        # AI integration
│   │   └── validation_service.py    # Input validation
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── base.py             # Abstract repository
│   │   ├── local_repository.py # File-based (dev)
│   │   └── postgres_repository.py # PostgreSQL (prod)
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py           # Settings management
│   │   ├── security.py         # Security utilities
│   │   └── exceptions.py       # Custom exceptions
│   └── utils/
│       ├── __init__.py
│       ├── file_utils.py       # Safe file handling
│       ├── hash_utils.py       # File hashing
│       └── logging.py          # Safe logging
├── tests/
│   ├── __init__.py
│   ├── conftest.py             # Test fixtures
│   ├── test_health.py
│   ├── test_assessments.py
│   ├── test_validation.py
│   ├── test_image_quality.py
│   └── test_openai_service.py
├── requirements.txt
├── .env.example
└── README.md
```

## Key Design Decisions

### 1. Repository Pattern
The storage layer uses an abstract interface (`base.py`) so that:
- Development uses local file storage (`local_repository.py`)
- Production uses PostgreSQL (`postgres_repository.py`)
- Business logic never depends on specific storage implementation

### 2. Structured AI Output
The OpenAI service uses:
- A carefully engineered system prompt
- JSON mode with strict schema validation
- Pydantic validation of all AI responses
- Retry logic with exponential backoff
- Graceful handling of malformed responses

### 3. Separation of Concerns
- **Routes** handle HTTP concerns (status codes, headers)
- **Services** contain business logic
- **Repositories** handle data persistence
- **Schemas** define data contracts
- **Utils** provide shared utilities

### 4. Security Layers
- Input validation at the route level
- File validation by magic bytes (not extensions)
- Safe filename generation (UUIDs)
- Rate limiting middleware
- No secrets in logs or responses
- CORS configuration
