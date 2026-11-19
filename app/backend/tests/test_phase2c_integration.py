"""
Phase 2C Tests — AI Service Integration

Tests for:
- Mock provider initialization and operation
- Schema validation
- Provider selection
- Error handling
- Assessment service integration
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.providers.mock_provider import MockProvider
from app.providers.registry import ProviderRegistry
from app.schemas.assessment import (
    AIAnalysisResponse,
    Assessment,
    AssessmentStatus,
    EvidenceQualityStatus,
    IssueSeverity,
    QualityIssue,
    ReviewTrigger,
)
from app.services.assessment_service import AssessmentService
from app.services.image_quality_service import ImageQualityService
from app.repositories.local_repository import LocalRepository
from app.utils.image_utils import ImageData
from app.core.exceptions import AIProviderError, AIProviderUnavailableError


# ============================================================================
# Mock Provider Tests
# ============================================================================

@pytest.mark.asyncio
async def test_mock_provider_initialization():
    """Test that mock provider initializes without errors."""
    provider = MockProvider()
    await provider.initialize()
    
    assert provider.name == "mock"
    assert provider.requires_api_key is False
    assert await provider.is_available() is True


@pytest.mark.asyncio
async def test_mock_provider_returns_schema_valid_response():
    """Test that mock provider returns schema-valid AIAnalysisResponse."""
    provider = MockProvider()
    await provider.initialize()
    
    # Create minimal test image data
    test_image = ImageData(
        content=b"fake_image_data",
        content_type="image/jpeg",
        filename="test.jpg",
        hash_sha256="abc123",
        width=100,
        height=100,
        format="JPEG"
    )
    
    response = await provider.analyze_images([test_image])
    
    # Verify response is AIAnalysisResponse
    assert isinstance(response, AIAnalysisResponse)
    
    # Verify required fields
    assert response.visual_observations is not None
    assert response.inferred is not None
    assert response.unknown is not None
    assert response.proposed_assessment is not None
    assert response.confidence >= 0.0 and response.confidence <= 1.0
    assert response.missing_evidence is not None
    assert response.recommended_next_steps is not None


@pytest.mark.asyncio
async def test_mock_provider_deterministic_mode():
    """Test that mock provider can be set to deterministic mode."""
    provider = MockProvider()
    await provider.initialize()
    
    # Force specific scenario
    MockProvider.force_scenario = "ferrous_rusted"
    
    test_image = ImageData(
        content=b"fake_image_data",
        content_type="image/jpeg",
        filename="test.jpg",
        hash_sha256="abc123",
        width=100,
        height=100,
        format="JPEG"
    )
    
    # Call multiple times — should return same scenario
    response1 = await provider.analyze_images([test_image])
    response2 = await provider.analyze_images([test_image])
    
    # Both should be ferrous
    assert response1.proposed_assessment.material_family == "ferrous"
    assert response2.proposed_assessment.material_family == "ferrous"
    
    # Clean up
    MockProvider.force_scenario = None


@pytest.mark.asyncio
async def test_mock_provider_separates_observed_inferred_unknown():
    """Test that mock provider clearly separates observations, inferences, unknowns."""
    provider = MockProvider()
    await provider.initialize()
    
    MockProvider.force_scenario = "ferrous_rusted"
    
    test_image = ImageData(
        content=b"fake_image_data",
        content_type="image/jpeg",
        filename="test.jpg",
        hash_sha256="abc123",
        width=100,
        height=100,
        format="JPEG"
    )
    
    response = await provider.analyze_images([test_image])
    
    # Verify separation
    assert len(response.visual_observations) > 0, "Should have observations"
    assert len(response.inferred) > 0, "Should have inferences"
    assert len(response.unknown) > 0, "Should have unknowns"
    
    # Verify inferences have confidence and limitations
    for inference in response.inferred:
        assert inference.confidence >= 0.0 and inference.confidence <= 1.0
        assert inference.limitations is not None
        assert len(inference.limitations) > 0
    
    # Verify unknowns have reasons
    for unknown in response.unknown:
        assert unknown.reason is not None
        assert len(unknown.reason) > 0
        assert unknown.required_evidence is not None
    
    # Clean up
    MockProvider.force_scenario = None


# ============================================================================
# Provider Registry Tests
# ============================================================================

@pytest.mark.asyncio
async def test_provider_registry_mock_selection():
    """Test that registry can select mock provider."""
    registry = ProviderRegistry()
    await registry.initialize("mock")
    
    provider = registry.get_active_provider()
    assert provider is not None
    assert provider.name == "mock"


@pytest.mark.asyncio
async def test_provider_registry_unknown_provider_raises_error():
    """Test that unknown provider name raises clear error."""
    registry = ProviderRegistry()
    
    with pytest.raises(AIProviderError) as exc_info:
        await registry.initialize("unknown_provider")
    
    assert "Unknown AI provider" in str(exc_info.value)
    assert "mock, openai" in str(exc_info.value)


@pytest.mark.asyncio
async def test_provider_registry_local_not_implemented():
    """Test that local provider raises not-implemented error."""
    registry = ProviderRegistry()
    
    with pytest.raises(AIProviderError) as exc_info:
        await registry.initialize("local")
    
    assert "not yet implemented" in str(exc_info.value)


@pytest.mark.asyncio
async def test_provider_registry_openai_without_key_falls_back():
    """Test that OpenAI without API key falls back to mock."""
    registry = ProviderRegistry()
    
    # Mock settings to have no API key
    with patch('app.providers.registry.settings') as mock_settings:
        mock_settings.openai_api_key = ""
        mock_settings.openai_model = "gpt-4o"
        
        await registry.initialize("openai")
        
        # Should fall back to mock
        provider = registry.get_active_provider()
        assert provider is not None
        assert provider.name == "mock"


@pytest.mark.asyncio
async def test_provider_registry_require_active_provider():
    """Test that require_active_provider raises error if no provider."""
    registry = ProviderRegistry()
    
    with pytest.raises(AIProviderUnavailableError):
        registry.require_active_provider()


# ============================================================================
# Schema Validation Tests
# ============================================================================

def test_ai_analysis_response_schema_validation():
    """Test that AIAnalysisResponse validates correctly."""
    # Valid response
    valid_data = {
        "visual_observations": [
            {
                "finding": "Rusty surface",
                "supporting_evidence": "Orange-brown discoloration",
                "category": "surface"
            }
        ],
        "inferred": [
            {
                "finding": "Likely ferrous material",
                "confidence": 0.75,
                "supporting_visual_evidence": "Rust pattern",
                "limitations": "Cannot determine exact alloy",
                "category": "material_family"
            }
        ],
        "unknown": [
            {
                "item": "Exact composition",
                "reason": "Visual inspection insufficient",
                "required_evidence": "XRF analysis"
            }
        ],
        "proposed_assessment": {
            "material_family": "ferrous",
            "scrap_form": "irregular",
            "surface_condition": "heavily_rusted",
            "visible_contamination": "none_visible",
            "description": "Rusted ferrous scrap",
            "estimated_grade_hint": None,
            "grade_hint_confidence": 0.0,
            "caveats": ["Grade unverified"]
        },
        "confidence": 0.75,
        "missing_evidence": ["Better lighting"],
        "recommended_next_steps": ["XRF analysis"],
        "scanner_xrf_recommended": True,
        "review_triggers": ["consequential_claim"]
    }
    
    response = AIAnalysisResponse(**valid_data)
    assert response.confidence == 0.75
    assert len(response.visual_observations) == 1
    assert len(response.inferred) == 1
    assert len(response.unknown) == 1


def test_ai_analysis_response_rejects_invalid_confidence():
    """Test that invalid confidence values are rejected."""
    invalid_data = {
        "visual_observations": [],
        "inferred": [
            {
                "finding": "Test",
                "confidence": 1.5,  # Invalid: > 1.0
                "supporting_visual_evidence": "Test",
                "limitations": "Test",
                "category": "material_family"
            }
        ],
        "unknown": [],
        "proposed_assessment": None,
        "confidence": 0.5,
        "missing_evidence": [],
        "recommended_next_steps": [],
        "scanner_xrf_recommended": False,
        "review_triggers": []
    }
    
    with pytest.raises(Exception):  # Pydantic ValidationError
        AIAnalysisResponse(**invalid_data)


# ============================================================================
# Assessment Service Integration Tests
# ============================================================================

@pytest.mark.asyncio
async def test_assessment_service_with_mock_provider():
    """Test assessment service integration with mock provider."""
    # Setup
    repository = MagicMock(spec=LocalRepository)
    repository.save_assessment = AsyncMock()
    
    quality_service = MagicMock(spec=ImageQualityService)
    quality_service.assess_quality.return_value = MagicMock(
        status=EvidenceQualityStatus.sufficient,
        overall_score=85,
        issues=[],
        recommended_additional_photos=[]
    )
    
    service = AssessmentService(repository, quality_service)
    
    # Initialize mock provider
    from app.providers.registry import provider_registry
    await provider_registry.initialize("mock")
    
    # Create test image
    test_image = ImageData(
        content=b"fake_image_data",
        content_type="image/jpeg",
        filename="test.jpg",
        hash_sha256="abc123",
        width=100,
        height=100,
        format="JPEG"
    )
    
    # Run assessment
    assessment = await service.create_assessment([test_image])
    
    # Verify assessment
    assert isinstance(assessment, Assessment)
    assert assessment.assessment_id.startswith("ASM-")
    assert assessment.status in [AssessmentStatus.completed, AssessmentStatus.requires_review]
    assert assessment.confidence >= 0.0 and assessment.confidence <= 1.0
    
    # Verify repository was called
    repository.save_assessment.assert_called_once()


@pytest.mark.asyncio
async def test_assessment_service_handles_insufficient_quality():
    """Test that assessment service handles insufficient image quality."""
    repository = MagicMock(spec=LocalRepository)
    repository.save_assessment = AsyncMock()
    
    quality_service = MagicMock(spec=ImageQualityService)
    quality_service.assess_quality.return_value = MagicMock(
        status=EvidenceQualityStatus.insufficient,
        overall_score=20,
        issues=[
            QualityIssue(
                issue="blur", severity=IssueSeverity.high, description="Too blurry"
            )
        ],
        recommended_additional_photos=["Retake photo"]
    )
    
    service = AssessmentService(repository, quality_service)
    
    test_image = ImageData(
        content=b"fake_image_data",
        content_type="image/jpeg",
        filename="test.jpg",
        hash_sha256="abc123",
        width=100,
        height=100,
        format="JPEG"
    )
    
    assessment = await service.create_assessment([test_image])
    
    # Should return early with insufficient quality
    assert assessment.status == AssessmentStatus.requires_review
    assert assessment.human_review_required is True
    assert ReviewTrigger.insufficient_evidence in assessment.human_review_reasons
    assert assessment.confidence == 0.0


# ============================================================================
# Error Handling Tests
# ============================================================================

@pytest.mark.asyncio
async def test_assessment_service_handles_provider_unavailable():
    """Test that assessment service handles unavailable provider."""
    repository = MagicMock(spec=LocalRepository)
    quality_service = MagicMock(spec=ImageQualityService)
    quality_service.assess_quality.return_value = MagicMock(
        status=EvidenceQualityStatus.sufficient,
        overall_score=85
    )
    
    service = AssessmentService(repository, quality_service)
    
    # Don't initialize provider
    from app.providers.registry import provider_registry
    provider_registry._active_provider = None
    
    test_image = ImageData(
        content=b"fake_image_data",
        content_type="image/jpeg",
        filename="test.jpg",
        hash_sha256="abc123",
        width=100,
        height=100,
        format="JPEG"
    )
    
    with pytest.raises(AIProviderUnavailableError):
        await service.create_assessment([test_image])


# ============================================================================
# Configuration Tests
# ============================================================================

def test_config_defaults_to_mock_provider():
    """Test that configuration defaults to mock provider."""
    from app.core.config import settings
    
    # Default should be mock
    assert settings.ai_provider == "mock"
    
    # OpenAI key should be empty by default
    assert settings.openai_api_key == ""


def test_config_does_not_expose_api_keys():
    """Test that configuration doesn't expose API keys in string representation."""
    from app.core.config import settings
    
    # Set a fake API key
    settings.openai_api_key = "sk-test-key-12345"
    
    # String representation should not contain the key
    config_str = str(settings)
    assert "sk-test-key-12345" not in config_str
    
    # Clean up
    settings.openai_api_key = ""


__all__ = [
    "test_mock_provider_initialization",
    "test_mock_provider_returns_schema_valid_response",
    "test_mock_provider_deterministic_mode",
    "test_mock_provider_separates_observed_inferred_unknown",
    "test_provider_registry_mock_selection",
    "test_provider_registry_unknown_provider_raises_error",
    "test_provider_registry_local_not_implemented",
    "test_provider_registry_openai_without_key_falls_back",
    "test_provider_registry_require_active_provider",
    "test_ai_analysis_response_schema_validation",
    "test_ai_analysis_response_rejects_invalid_confidence",
    "test_assessment_service_with_mock_provider",
    "test_assessment_service_handles_insufficient_quality",
    "test_assessment_service_handles_provider_unavailable",
    "test_config_defaults_to_mock_provider",
    "test_config_does_not_expose_api_keys",
]
