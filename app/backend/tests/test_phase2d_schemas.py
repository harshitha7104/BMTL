"""
Phase 2D Tests — Assessment Schemas and Data Integrity

Tests for:
- Schema validation (valid/invalid assessments)
- Evidence items tracking
- Schema version tracking
- AI output validation rules
- Immutability protection
- Feedback separation
- Frontend/backend type compatibility
"""
import pytest
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from app.schemas.assessment import (
    AIAnalysisResponse,
    Assessment,
    AssessmentStatus,
    EvidenceItem,
    EvidenceQuality,
    EvidenceQualityStatus,
    FeedbackCategory,
    FeedbackCorrections,
    FeedbackRecord,
    Inference,
    InferenceCategory,
    MaterialFamily,
    Observation,
    ObservationCategory,
    ProcessingMetadata,
    ProposedAssessment,
    QualityIssue,
    IssueSeverity,
    ReviewTrigger,
    ScrapForm,
    SCHEMA_VERSION,
    SurfaceCondition,
    Unknown,
    VerificationStatus,
    VisibleContamination,
)
from app.repositories.local_repository import LocalRepository
from app.utils.image_utils import ImageData


# ============================================================================
# Schema Validation Tests
# ============================================================================

class TestAssessmentSchemaValidation:
    """Test Assessment schema validation."""
    
    def _make_valid_assessment(self, **overrides) -> Assessment:
        """Create a valid assessment for testing."""
        base = {
            "assessment_id": "ASM-TEST123",
            "schema_version": SCHEMA_VERSION,
            "evidence_quality": EvidenceQuality(
                status=EvidenceQualityStatus.sufficient,
                issues=[],
                recommended_additional_photos=[],
                human_review_required=False,
                overall_score=85,
            ),
            "evidence_items": [],
            "material_family": MaterialFamily.ferrous,
            "scrap_form": ScrapForm.irregular,
            "visible_surface_condition": SurfaceCondition.heavily_rusted,
            "visible_contamination": VisibleContamination.none_visible,
            "visual_observations": [
                Observation(
                    finding="Rusty surface",
                    supporting_evidence="Orange-brown discoloration visible",
                    category=ObservationCategory.surface,
                )
            ],
            "observed": [
                Observation(
                    finding="Rusty surface",
                    supporting_evidence="Orange-brown discoloration visible",
                    category=ObservationCategory.surface,
                )
            ],
            "inferred": [
                Inference(
                    finding="Likely ferrous material",
                    confidence=0.75,
                    supporting_visual_evidence="Rust pattern",
                    limitations="Cannot determine exact alloy without XRF",
                    category=InferenceCategory.material_family,
                )
            ],
            "unknown": [
                Unknown(
                    item="Exact alloy composition",
                    reason="Visual inspection insufficient",
                    required_evidence="XRF spectroscopy",
                )
            ],
            "proposed_assessment": ProposedAssessment(
                material_family=MaterialFamily.ferrous,
                scrap_form=ScrapForm.irregular,
                surface_condition=SurfaceCondition.heavily_rusted,
                visible_contamination=VisibleContamination.none_visible,
                description="Rusted ferrous scrap material",
                estimated_grade_hint=None,
                grade_hint_confidence=0.0,
                caveats=["Grade unverified"],
            ),
            "confidence": 0.75,
            "missing_evidence": ["Better lighting"],
            "recommended_next_steps": ["XRF analysis"],
            "human_review_required": False,
            "human_review_reasons": [],
            "scanner_xrf_recommended": True,
            "processing_metadata": ProcessingMetadata(
                model_used="mock",
                processing_time_ms=100,
                tokens_used=0,
                image_count=1,
                total_image_size_bytes=100000,
                validation_passed=True,
                retry_count=0,
                provider_id="mock",
            ),
            "status": AssessmentStatus.completed,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        base.update(overrides)
        return Assessment(**base)
    
    def test_valid_assessment_schema(self):
        """Test that a valid assessment passes schema validation."""
        assessment = self._make_valid_assessment()
        assert assessment.assessment_id == "ASM-TEST123"
        assert assessment.schema_version == SCHEMA_VERSION
        assert assessment.confidence == 0.75
    
    def test_assessment_has_schema_version(self):
        """Test that assessment includes schema version."""
        assessment = self._make_valid_assessment()
        assert assessment.schema_version == SCHEMA_VERSION
        assert assessment.schema_version == "1.0.0"
    
    def test_assessment_has_evidence_items(self):
        """Test that assessment includes evidence items list."""
        evidence_item = EvidenceItem(
            evidence_id="EVD-ABC123",
            original_filename="test.jpg",
            content_type="image/jpeg",
            size_bytes=100000,
            hash_sha256="abc123def456",
            width=1024,
            height=768,
            quality_status=EvidenceQualityStatus.sufficient,
            quality_score=85,
            quality_issues=[],
        )
        assessment = self._make_valid_assessment(evidence_items=[evidence_item])
        assert len(assessment.evidence_items) == 1
        assert assessment.evidence_items[0].evidence_id == "EVD-ABC123"
    
    def test_invalid_confidence_too_high(self):
        """Test that confidence > 1.0 is rejected."""
        with pytest.raises(Exception):
            self._make_valid_assessment(confidence=1.5)
    
    def test_invalid_confidence_negative(self):
        """Test that negative confidence is rejected."""
        with pytest.raises(Exception):
            self._make_valid_assessment(confidence=-0.1)
    
    def test_invalid_review_trigger(self):
        """Test that invalid review trigger is rejected."""
        with pytest.raises(Exception):
            self._make_valid_assessment(
                human_review_reasons=["invalid_trigger_value"]
            )
    
    def test_valid_review_triggers(self):
        """Test that all valid review triggers are accepted."""
        all_triggers = list(ReviewTrigger)
        assessment = self._make_valid_assessment(
            human_review_reasons=all_triggers,
            human_review_required=True,
        )
        assert len(assessment.human_review_reasons) == len(all_triggers)


# ============================================================================
# AI Output Validation Tests
# ============================================================================

class TestAIOutputValidation:
    """Test AIAnalysisResponse validation rules."""
    
    def test_valid_ai_response_with_observations(self):
        """Test valid AI response with observations."""
        response = AIAnalysisResponse(
            visual_observations=[
                Observation(
                    finding="Rusty surface",
                    supporting_evidence="Orange discoloration",
                    category=ObservationCategory.surface,
                )
            ],
            inferred=[],
            unknown=[],
            confidence=0.8,
        )
        assert len(response.visual_observations) == 1
    
    def test_valid_ai_response_with_unknowns_only(self):
        """Test valid AI response with only unknowns (no observations)."""
        response = AIAnalysisResponse(
            visual_observations=[],
            inferred=[],
            unknown=[
                Unknown(
                    item="Material type",
                    reason="Image too blurry",
                    required_evidence="Clear photograph",
                )
            ],
            confidence=0.1,
        )
        assert len(response.unknown) == 1
    
    def test_empty_ai_response_rejected(self):
        """Test that completely empty AI response is rejected."""
        with pytest.raises(Exception) as exc_info:
            AIAnalysisResponse(
                visual_observations=[],
                inferred=[],
                unknown=[],
                confidence=0.5,
            )
        assert "at least one observation or one unknown" in str(exc_info.value)
    
    def test_low_confidence_without_unknowns_rejected(self):
        """Test that low confidence without unknowns is rejected."""
        with pytest.raises(Exception) as exc_info:
            AIAnalysisResponse(
                visual_observations=[
                    Observation(
                        finding="Something",
                        supporting_evidence="Visible",
                        category=ObservationCategory.other,
                    )
                ],
                inferred=[],
                unknown=[],
                confidence=0.2,  # Low confidence
            )
        assert "Low confidence" in str(exc_info.value)
    
    def test_inference_without_limitations_rejected(self):
        """Test that inference without limitations is rejected."""
        with pytest.raises(Exception) as exc_info:
            AIAnalysisResponse(
                visual_observations=[
                    Observation(
                        finding="Something",
                        supporting_evidence="Visible",
                        category=ObservationCategory.other,
                    )
                ],
                inferred=[
                    Inference(
                        finding="Likely steel",
                        confidence=0.7,
                        supporting_visual_evidence="Color",
                        limitations="",  # Empty limitations
                        category=InferenceCategory.material_family,
                    )
                ],
                unknown=[],
                confidence=0.7,
            )
        assert "limitations" in str(exc_info.value).lower()
    
    def test_valid_inference_with_limitations(self):
        """Test that inference with proper limitations is accepted."""
        response = AIAnalysisResponse(
            visual_observations=[
                Observation(
                    finding="Something",
                    supporting_evidence="Visible",
                    category=ObservationCategory.other,
                )
            ],
            inferred=[
                Inference(
                    finding="Likely steel",
                    confidence=0.7,
                    supporting_visual_evidence="Color",
                    limitations="Cannot confirm without XRF analysis",
                    category=InferenceCategory.material_family,
                )
            ],
            unknown=[],
            confidence=0.7,
        )
        assert len(response.inferred) == 1


# ============================================================================
# Evidence Item Tests
# ============================================================================

class TestEvidenceItem:
    """Test EvidenceItem schema."""
    
    def test_valid_evidence_item(self):
        """Test creating a valid evidence item."""
        item = EvidenceItem(
            evidence_id="EVD-ABC123",
            original_filename="scrap_photo.jpg",
            content_type="image/jpeg",
            size_bytes=250000,
            hash_sha256="a" * 64,
            width=1920,
            height=1080,
            quality_status=EvidenceQualityStatus.sufficient,
            quality_score=85,
            quality_issues=[],
        )
        assert item.evidence_id == "EVD-ABC123"
        assert item.quality_score == 85
    
    def test_evidence_item_with_quality_issues(self):
        """Test evidence item with quality issues."""
        item = EvidenceItem(
            evidence_id="EVD-DEF456",
            original_filename="dark_photo.jpg",
            content_type="image/jpeg",
            size_bytes=150000,
            hash_sha256="b" * 64,
            width=800,
            height=600,
            quality_status=EvidenceQualityStatus.partially_sufficient,
            quality_score=45,
            quality_issues=[
                QualityIssue(
                    issue="too_dark",
                    severity=IssueSeverity.medium,
                    description="Image is underexposed",
                )
            ],
        )
        assert len(item.quality_issues) == 1
        assert item.quality_issues[0].severity == IssueSeverity.medium
    
    def test_evidence_item_invalid_score_too_high(self):
        """Test that quality score > 100 is rejected."""
        with pytest.raises(Exception):
            EvidenceItem(
                evidence_id="EVD-TEST",
                original_filename="test.jpg",
                content_type="image/jpeg",
                size_bytes=100000,
                hash_sha256="c" * 64,
                quality_status=EvidenceQualityStatus.sufficient,
                quality_score=150,  # Invalid
                quality_issues=[],
            )


# ============================================================================
# Feedback Schema Tests
# ============================================================================

class TestFeedbackSchema:
    """Test feedback schema and separation from assessment."""
    
    def test_valid_feedback_record(self):
        """Test creating a valid feedback record."""
        feedback = FeedbackRecord(
            feedback_id="FB-ABC123",
            assessment_id="ASM-TEST123",
            reviewer_name="John Doe",
            feedback_category=FeedbackCategory.correction,
            corrections=FeedbackCorrections(
                material_family=MaterialFamily.non_ferrous,
                additional_notes="Actually aluminum, not steel",
            ),
            verified=False,
            verification_status=VerificationStatus.unverified,
            submitted_at=datetime.utcnow(),
        )
        assert feedback.feedback_id == "FB-ABC123"
        assert feedback.feedback_category == FeedbackCategory.correction
        assert feedback.verification_status == VerificationStatus.unverified
    
    def test_all_feedback_categories(self):
        """Test all feedback categories are valid."""
        for category in FeedbackCategory:
            feedback = FeedbackRecord(
                feedback_id=f"FB-{category.value}",
                assessment_id="ASM-TEST",
                reviewer_name="Tester",
                feedback_category=category,
                corrections=FeedbackCorrections(),
                verified=False,
                verification_status=VerificationStatus.unverified,
                submitted_at=datetime.utcnow(),
            )
            assert feedback.feedback_category == category
    
    def test_feedback_does_not_modify_assessment(self):
        """
        Test that feedback record is separate from assessment.
        This is a design test — feedback should never be part of Assessment.
        """
        # Create assessment
        assessment_fields = set(Assessment.model_fields.keys())
        
        # Create feedback
        feedback_fields = set(FeedbackRecord.model_fields.keys())
        
        # Feedback should have its own fields, not modify assessment
        assert "feedback_id" in feedback_fields
        assert "feedback_id" not in assessment_fields
        assert "feedback_category" in feedback_fields
        assert "feedback_category" not in assessment_fields


# ============================================================================
# Immutability Tests
# ============================================================================

class TestImmutability:
    """Test that assessments cannot be silently overwritten."""
    
    @pytest.mark.asyncio
    async def test_repository_rejects_overwrite_by_default(self, tmp_path):
        """Test that repository rejects overwriting existing assessments."""
        repo = LocalRepository(str(tmp_path))
        await repo.initialize()
        
        # Create and save assessment
        assessment = self._make_minimal_assessment("ASM-TEST1")
        await repo.save_assessment(assessment)
        
        # Try to save again — should fail
        with pytest.raises(ValueError) as exc_info:
            await repo.save_assessment(assessment)
        assert "already exists" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_repository_allows_explicit_overwrite(self, tmp_path):
        """Test that explicit overwrite flag allows saving."""
        repo = LocalRepository(str(tmp_path))
        await repo.initialize()
        
        # Create and save assessment
        assessment = self._make_minimal_assessment("ASM-TEST2")
        await repo.save_assessment(assessment)
        
        # Save again with overwrite=True — should succeed
        await repo.save_assessment(assessment, overwrite=True)
        
        # Verify it's still there
        loaded = await repo.get_assessment("ASM-TEST2")
        assert loaded is not None
    
    @pytest.mark.asyncio
    async def test_original_assessment_preserved_after_feedback(self, tmp_path):
        """Test that original assessment is preserved when feedback is added."""
        repo = LocalRepository(str(tmp_path))
        await repo.initialize()
        
        # Create and save assessment
        original = self._make_minimal_assessment("ASM-TEST3")
        original_confidence = original.confidence
        await repo.save_assessment(original)
        
        # Add feedback
        feedback = FeedbackRecord(
            feedback_id="FB-TEST1",
            assessment_id="ASM-TEST3",
            reviewer_name="Reviewer",
            feedback_category=FeedbackCategory.correction,
            corrections=FeedbackCorrections(
                material_family=MaterialFamily.non_ferrous,
            ),
            confidence_override=0.9,
            verified=False,
            verification_status=VerificationStatus.unverified,
            submitted_at=datetime.utcnow(),
        )
        await repo.save_feedback(feedback)
        
        # Load original assessment — should be unchanged
        loaded = await repo.get_assessment("ASM-TEST3")
        assert loaded is not None
        assert loaded.confidence == original_confidence
        assert loaded.material_family == original.material_family
        
        # Feedback should be separate
        feedbacks = await repo.get_feedback("ASM-TEST3")
        assert len(feedbacks) == 1
        assert feedbacks[0].confidence_override == 0.9
    
    def _make_minimal_assessment(self, assessment_id: str) -> Assessment:
        """Create a minimal valid assessment for testing."""
        return Assessment(
            assessment_id=assessment_id,
            schema_version=SCHEMA_VERSION,
            evidence_quality=EvidenceQuality(
                status=EvidenceQualityStatus.sufficient,
                issues=[],
                recommended_additional_photos=[],
                human_review_required=False,
                overall_score=85,
            ),
            evidence_items=[],
            material_family=None,
            scrap_form=None,
            visible_surface_condition=None,
            visible_contamination=None,
            visual_observations=[],
            observed=[],
            inferred=[],
            unknown=[
                Unknown(
                    item="Material type",
                    reason="Insufficient evidence",
                    required_evidence="Better images",
                )
            ],
            proposed_assessment=None,
            confidence=0.0,
            missing_evidence=[],
            recommended_next_steps=[],
            human_review_required=True,
            human_review_reasons=[ReviewTrigger.insufficient_evidence],
            scanner_xrf_recommended=False,
            processing_metadata=ProcessingMetadata(
                model_used="mock",
                processing_time_ms=0,
                tokens_used=0,
                image_count=1,
                total_image_size_bytes=100000,
                validation_passed=True,
                retry_count=0,
                provider_id="mock",
            ),
            status=AssessmentStatus.requires_review,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )


# ============================================================================
# Persistence Tests
# ============================================================================

class TestPersistence:
    """Test assessment persistence and retrieval."""
    
    @pytest.mark.asyncio
    async def test_save_and_retrieve_assessment(self, tmp_path):
        """Test saving and retrieving an assessment."""
        repo = LocalRepository(str(tmp_path))
        await repo.initialize()
        
        assessment = self._make_minimal_assessment("ASM-PERSIST1")
        await repo.save_assessment(assessment)
        
        loaded = await repo.get_assessment("ASM-PERSIST1")
        assert loaded is not None
        assert loaded.assessment_id == "ASM-PERSIST1"
        assert loaded.schema_version == SCHEMA_VERSION
    
    @pytest.mark.asyncio
    async def test_list_assessments(self, tmp_path):
        """Test listing assessments."""
        repo = LocalRepository(str(tmp_path))
        await repo.initialize()
        
        # Save multiple assessments
        for i in range(3):
            assessment = self._make_minimal_assessment(f"ASM-LIST{i}")
            await repo.save_assessment(assessment)
        
        # List all
        assessments = await repo.list_assessments()
        assert len(assessments) == 3
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_assessment(self, tmp_path):
        """Test getting a nonexistent assessment returns None."""
        repo = LocalRepository(str(tmp_path))
        await repo.initialize()
        
        result = await repo.get_assessment("ASM-NONEXISTENT")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_assessment_json_serialization(self, tmp_path):
        """Test that assessment can be serialized to/from JSON."""
        repo = LocalRepository(str(tmp_path))
        await repo.initialize()
        
        assessment = self._make_minimal_assessment("ASM-JSON1")
        await repo.save_assessment(assessment)
        
        # Read raw JSON
        filepath = tmp_path / "assessments" / "ASM-JSON1.json"
        with open(filepath) as f:
            raw_data = json.load(f)
        
        # Verify key fields are present
        assert raw_data["assessment_id"] == "ASM-JSON1"
        assert raw_data["schema_version"] == SCHEMA_VERSION
        assert "evidence_items" in raw_data
        assert "processing_metadata" in raw_data
        
        # Verify it can be loaded back
        loaded = await repo.get_assessment("ASM-JSON1")
        assert loaded is not None
    
    def _make_minimal_assessment(self, assessment_id: str) -> Assessment:
        """Create a minimal valid assessment for testing."""
        return Assessment(
            assessment_id=assessment_id,
            schema_version=SCHEMA_VERSION,
            evidence_quality=EvidenceQuality(
                status=EvidenceQualityStatus.sufficient,
                issues=[],
                recommended_additional_photos=[],
                human_review_required=False,
                overall_score=85,
            ),
            evidence_items=[],
            material_family=None,
            scrap_form=None,
            visible_surface_condition=None,
            visible_contamination=None,
            visual_observations=[],
            observed=[],
            inferred=[],
            unknown=[
                Unknown(
                    item="Material type",
                    reason="Insufficient evidence",
                    required_evidence="Better images",
                )
            ],
            proposed_assessment=None,
            confidence=0.0,
            missing_evidence=[],
            recommended_next_steps=[],
            human_review_required=True,
            human_review_reasons=[ReviewTrigger.insufficient_evidence],
            scanner_xrf_recommended=False,
            processing_metadata=ProcessingMetadata(
                model_used="mock",
                processing_time_ms=0,
                tokens_used=0,
                image_count=1,
                total_image_size_bytes=100000,
                validation_passed=True,
                retry_count=0,
                provider_id="mock",
            ),
            status=AssessmentStatus.requires_review,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )


# ============================================================================
# Frontend/Backend Compatibility Tests
# ============================================================================

class TestFrontendBackendCompatibility:
    """Test that backend schemas are compatible with frontend types."""
    
    def test_assessment_has_all_frontend_fields(self):
        """Test that Assessment has all fields expected by frontend."""
        # These fields must exist in both backend and frontend
        required_fields = [
            "assessment_id",
            "schema_version",
            "evidence_quality",
            "evidence_items",
            "material_family",
            "scrap_form",
            "visible_surface_condition",
            "visible_contamination",
            "visual_observations",
            "observed",
            "inferred",
            "unknown",
            "proposed_assessment",
            "confidence",
            "missing_evidence",
            "recommended_next_steps",
            "human_review_required",
            "human_review_reasons",
            "scanner_xrf_recommended",
            "processing_metadata",
            "status",
            "created_at",
            "updated_at",
        ]
        
        for field in required_fields:
            assert field in Assessment.model_fields, f"Missing field: {field}"
    
    def test_processing_metadata_has_provider_id(self):
        """Test that ProcessingMetadata has provider_id for frontend."""
        assert "provider_id" in ProcessingMetadata.model_fields
    
    def test_review_trigger_values_match_frontend(self):
        """Test that ReviewTrigger values match frontend type definition."""
        expected_triggers = [
            "insufficient_evidence",
            "high_uncertainty",
            "conflicting_images",
            "consequential_claim",
            "unsupported_conclusion",
            "hazardous_material",
            "mixed_material",
            "electronic_scrap",
            "low_quality_images",
            "model_refusal",
            "schema_validation_failure",
            "processing_error",
        ]
        
        actual_triggers = [t.value for t in ReviewTrigger]
        for trigger in expected_triggers:
            assert trigger in actual_triggers, f"Missing trigger: {trigger}"
    
    def test_feedback_category_values_match_frontend(self):
        """Test that FeedbackCategory values match frontend type definition."""
        expected_categories = [
            "correction",
            "clarification",
            "disagreement",
            "confirmation",
            "additional_info",
            "other",
        ]
        
        actual_categories = [c.value for c in FeedbackCategory]
        for category in expected_categories:
            assert category in actual_categories, f"Missing category: {category}"
    
    def test_schema_version_format(self):
        """Test that schema version follows semver format."""
        parts = SCHEMA_VERSION.split(".")
        assert len(parts) == 3
        for part in parts:
            assert part.isdigit()


__all__ = [
    "TestAssessmentSchemaValidation",
    "TestAIOutputValidation",
    "TestEvidenceItem",
    "TestFeedbackSchema",
    "TestImmutability",
    "TestPersistence",
    "TestFrontendBackendCompatibility",
]
