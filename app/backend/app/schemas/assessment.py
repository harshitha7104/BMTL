"""
Pydantic schemas for assessment data models.

These define the strict contracts for AI output validation.
Field names match the frontend TypeScript types for consistency.

SCHEMA VERSION: 1.0.0
When making breaking changes to this schema, increment SCHEMA_VERSION
and add migration logic in the repository layer.
"""
from datetime import datetime
from enum import Enum
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict

# Schema version for migration tracking
SCHEMA_VERSION = "1.0.0"


# --- Enums (Controlled Vocabulary) ---

class EvidenceQualityStatus(str, Enum):
    sufficient = "sufficient"
    partially_sufficient = "partially_sufficient"
    insufficient = "insufficient"


class MaterialFamily(str, Enum):
    ferrous = "ferrous"
    non_ferrous = "non_ferrous"
    mixed = "mixed"
    electronic = "electronic"
    plastic = "plastic"
    organic = "organic"
    hazardous = "hazardous"
    unidentifiable = "unidentifiable"


class ScrapForm(str, Enum):
    sheet = "sheet"
    bar = "bar"
    pipe = "pipe"
    wire = "wire"
    turning = "turning"
    casting = "casting"
    forging = "forging"
    machined_part = "machined_part"
    electronic_component = "electronic_component"
    fragment = "fragment"
    irregular = "irregular"
    unidentifiable = "unidentifiable"


class SurfaceCondition(str, Enum):
    clean = "clean"
    lightly_rusted = "lightly_rusted"
    heavily_rusted = "heavily_rusted"
    painted = "painted"
    coated = "coated"
    oxidized = "oxidized"
    contaminated = "contaminated"
    corroded = "corroded"
    unidentifiable = "unidentifiable"


class VisibleContamination(str, Enum):
    none_visible = "none_visible"
    oil_grease = "oil_grease"
    dirt_soil = "dirt_soil"
    paint = "paint"
    rubber = "rubber"
    plastic = "plastic"
    concrete = "concrete"
    organic = "organic"
    chemical_residue = "chemical_residue"
    unknown = "unknown"


class AssessmentStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    requires_review = "requires_review"


class IssueSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ObservationCategory(str, Enum):
    surface = "surface"
    shape = "shape"
    color = "color"
    texture = "texture"
    contamination = "contamination"
    other = "other"


class InferenceCategory(str, Enum):
    material_family = "material_family"
    scrap_form = "scrap_form"
    condition = "condition"
    contamination = "contamination"
    other = "other"


class ReviewTrigger(str, Enum):
    """
    Qualitative triggers for human review.
    NOT based on numeric confidence thresholds.
    """
    insufficient_evidence = "insufficient_evidence"
    high_uncertainty = "high_uncertainty"
    conflicting_images = "conflicting_images"
    consequential_claim = "consequential_claim"
    unsupported_conclusion = "unsupported_conclusion"
    hazardous_material = "hazardous_material"
    mixed_material = "mixed_material"
    electronic_scrap = "electronic_scrap"
    low_quality_images = "low_quality_images"
    model_refusal = "model_refusal"
    schema_validation_failure = "schema_validation_failure"
    processing_error = "processing_error"


class VerificationStatus(str, Enum):
    unverified = "unverified"
    partially_verified = "partially_verified"
    verified = "verified"


# --- Component Models ---

class QualityIssue(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    issue: str = Field(..., min_length=1, max_length=100)
    severity: IssueSeverity
    description: str = Field(..., min_length=1, max_length=500)


class EvidenceQuality(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: EvidenceQualityStatus
    issues: List[QualityIssue] = Field(default_factory=list)
    recommended_additional_photos: List[str] = Field(default_factory=list)
    human_review_required: bool = False
    overall_score: int = Field(..., ge=0, le=100)


class Observation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    finding: str = Field(..., min_length=1, max_length=500)
    supporting_evidence: str = Field(..., min_length=1, max_length=500)
    category: ObservationCategory


class Inference(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    finding: str = Field(..., min_length=1, max_length=500)
    confidence: float = Field(..., ge=0.0, le=1.0)
    supporting_visual_evidence: str = Field(..., min_length=1, max_length=500)
    limitations: str = Field(..., min_length=1, max_length=500)
    category: InferenceCategory

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if v < 0 or v > 1:
            raise ValueError("Confidence must be between 0 and 1")
        return round(v, 2)


class Unknown(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item: str = Field(..., min_length=1, max_length=200)
    reason: str = Field(..., min_length=1, max_length=500)
    required_evidence: str = Field(..., min_length=1, max_length=500)


class ProposedAssessment(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    material_family: MaterialFamily
    scrap_form: ScrapForm
    surface_condition: SurfaceCondition
    visible_contamination: VisibleContamination
    description: str = Field(..., min_length=10, max_length=1000)
    estimated_grade_hint: Optional[str] = Field(None, max_length=200)
    grade_hint_confidence: float = Field(0.0, ge=0.0, le=1.0)
    caveats: List[str] = Field(default_factory=list)


class ProcessingMetadata(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    model_used: str
    processing_time_ms: int
    tokens_used: int = 0
    image_count: int
    total_image_size_bytes: int
    validation_passed: bool
    retry_count: int = 0
    provider_id: str = "mock"


class EvidenceItem(BaseModel):
    """
    Per-image evidence record stored with the assessment.
    Tracks individual image metadata and quality without storing
    unnecessary sensitive information.
    """
    model_config = ConfigDict(from_attributes=True)

    evidence_id: str = Field(..., description="Unique ID for this evidence item")
    original_filename: str = Field(..., description="Original filename (sanitized)")
    content_type: str = Field(..., description="Detected MIME type")
    size_bytes: int = Field(..., ge=0, description="File size in bytes")
    hash_sha256: str = Field(..., description="SHA-256 hash for integrity/dedup")
    width: Optional[int] = Field(None, ge=0, description="Image width in pixels")
    height: Optional[int] = Field(None, ge=0, description="Image height in pixels")
    quality_status: EvidenceQualityStatus = Field(
        ..., description="Quality assessment for this specific image"
    )
    quality_score: int = Field(
        ..., ge=0, le=100, description="Quality score 0-100"
    )
    quality_issues: List[QualityIssue] = Field(
        default_factory=list, description="Issues detected in this image"
    )


# --- Main Assessment Model ---

class Assessment(BaseModel):
    """
    Complete assessment record.
    
    IMMUTABILITY: Once created, the original AI output fields should not be
    modified. Human corrections are stored separately as FeedbackRecord.
    
    SCHEMA VERSION: Track schema evolution for migration support.
    """
    model_config = ConfigDict(from_attributes=True)

    # Identity
    assessment_id: str
    schema_version: str = Field(
        default=SCHEMA_VERSION,
        description="Schema version for migration tracking"
    )
    
    # Evidence
    evidence_quality: EvidenceQuality
    evidence_items: List[EvidenceItem] = Field(
        default_factory=list,
        description="Per-image evidence records"
    )
    
    # Classification (top-level convenience fields)
    material_family: Optional[MaterialFamily] = None
    scrap_form: Optional[ScrapForm] = None
    visible_surface_condition: Optional[SurfaceCondition] = None
    visible_contamination: Optional[VisibleContamination] = None
    
    # Findings — clearly separated categories
    visual_observations: List[Observation] = Field(
        default_factory=list,
        description="Directly visible characteristics (OBSERVED)"
    )
    observed: List[Observation] = Field(
        default_factory=list,
        description="Alias for visual_observations — directly visible characteristics"
    )
    inferred: List[Inference] = Field(
        default_factory=list,
        description="Tentative interpretations with confidence (INFERRED)"
    )
    unknown: List[Unknown] = Field(
        default_factory=list,
        description="Cannot be determined from available evidence (UNKNOWN)"
    )
    
    # Assessment summary
    proposed_assessment: Optional[ProposedAssessment] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    missing_evidence: List[str] = Field(default_factory=list)
    recommended_next_steps: List[str] = Field(default_factory=list)
    
    # Review
    human_review_required: bool = False
    human_review_reasons: List[ReviewTrigger] = Field(default_factory=list)
    scanner_xrf_recommended: bool = False
    
    # Processing
    processing_metadata: ProcessingMetadata
    
    # Status and timestamps
    status: AssessmentStatus = AssessmentStatus.pending
    created_at: datetime
    updated_at: datetime


# --- Image Metadata ---

class ImageMetadata(BaseModel):
    """Metadata for a stored image file."""
    model_config = ConfigDict(from_attributes=True)

    filename: str
    original_filename: str
    content_type: str
    size_bytes: int
    hash_sha256: str
    width: Optional[int] = None
    height: Optional[int] = None
    stored_path: str


# --- AI Provider Response Schema ---

class AIAnalysisResponse(BaseModel):
    """
    Schema that AI providers must conform to.
    Validated after every AI call before use.
    
    VALIDATION RULES:
    - At least one observation OR one unknown must be present
    - If confidence < 0.3, at least one unknown should explain why
    - All inferences must have limitations documented
    - Review triggers should be populated when appropriate
    """
    visual_observations: List[Observation] = Field(default_factory=list)
    inferred: List[Inference] = Field(default_factory=list)
    unknown: List[Unknown] = Field(default_factory=list)
    proposed_assessment: Optional[ProposedAssessment] = None
    missing_evidence: List[str] = Field(default_factory=list)
    recommended_next_steps: List[str] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    scanner_xrf_recommended: bool = False
    review_triggers: List[ReviewTrigger] = Field(default_factory=list)
    
    @model_validator(mode="after")
    def validate_content_requirements(self):
        """
        Validate that AI response has meaningful content.
        
        Rules:
        1. Must have at least one observation OR one unknown
        2. Low confidence should have unknowns explaining why
        3. All inferences must have limitations
        """
        # Rule 1: Must have some content
        if not self.visual_observations and not self.unknown:
            raise ValueError(
                "AI response must contain at least one observation or one unknown item. "
                "Empty responses are not valid."
            )
        
        # Rule 2: Low confidence should have unknowns
        if self.confidence < 0.3 and not self.unknown:
            raise ValueError(
                f"Low confidence ({self.confidence}) response must include "
                "unknown items explaining what cannot be determined."
            )
        
        # Rule 3: All inferences must have limitations
        for i, inference in enumerate(self.inferred):
            if not inference.limitations or len(inference.limitations.strip()) < 5:
                raise ValueError(
                    f"Inference #{i+1} must document its limitations. "
                    "All inferences are tentative and must state what they cannot determine."
                )
        
        return self


# --- Feedback Record (Stored SEPARATELY from AI output) ---

class FeedbackCategory(str, Enum):
    """Category of feedback provided by reviewer."""
    correction = "correction"          # Factual correction to AI output
    clarification = "clarification"    # Additional context or explanation
    disagreement = "disagreement"      # Disagrees with AI assessment
    confirmation = "confirmation"      # Confirms AI assessment is correct
    additional_info = "additional_info"  # Provides new information
    other = "other"


class FeedbackCorrections(BaseModel):
    """Corrections to the original AI assessment."""
    material_family: Optional[MaterialFamily] = None
    scrap_form: Optional[ScrapForm] = None
    surface_condition: Optional[SurfaceCondition] = None
    contamination: Optional[VisibleContamination] = None
    additional_notes: Optional[str] = Field(None, max_length=2000)


class FeedbackSubmission(BaseModel):
    """Request schema for feedback submission."""
    reviewer_name: str = Field(..., min_length=1, max_length=100)
    feedback_category: FeedbackCategory = Field(
        default=FeedbackCategory.correction,
        description="Category of feedback being provided"
    )
    corrections: FeedbackCorrections = Field(default_factory=FeedbackCorrections)
    confidence_override: Optional[float] = Field(None, ge=0.0, le=1.0)
    verified: bool = False


class FeedbackRecord(BaseModel):
    """
    Stored feedback record — SEPARATE from original AI assessment.
    
    IMMUTABILITY PRINCIPLE:
    - Original AI output is NEVER modified by feedback
    - Feedback is stored as an independent record
    - Multiple feedback records can exist for one assessment
    - No automatic retraining uses unverified feedback
    """
    model_config = ConfigDict(from_attributes=True)

    feedback_id: str
    assessment_id: str
    reviewer_name: str
    feedback_category: FeedbackCategory = Field(
        default=FeedbackCategory.correction,
        description="Category of feedback provided"
    )
    corrections: FeedbackCorrections
    confidence_override: Optional[float] = None
    verified: bool = False
    verification_status: VerificationStatus = VerificationStatus.unverified
    submitted_at: datetime


# --- API Response Schemas ---

class APIResponse(BaseModel):
    """Standard API response wrapper."""
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None
    message: Optional[str] = None


class AssessmentResponse(APIResponse):
    data: Optional[Assessment] = None


class AssessmentListResponse(APIResponse):
    data: Optional[List[Assessment]] = None
    count: int = 0


class FeedbackResponse(APIResponse):
    data: Optional[FeedbackRecord] = None


class HealthResponse(BaseModel):
    status: str
    version: str
    ai_provider: str
    timestamp: datetime
