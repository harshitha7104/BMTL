"""
Pydantic schemas for assessment data models.
These define the strict contracts for AI output validation.
"""
from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


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


# --- Component Models ---

class QualityIssue(BaseModel):
    issue: str = Field(..., min_length=1, max_length=100)
    severity: IssueSeverity
    description: str = Field(..., min_length=1, max_length=500)


class EvidenceQuality(BaseModel):
    status: EvidenceQualityStatus
    issues: List[QualityIssue] = Field(default_factory=list)
    recommended_additional_photos: List[str] = Field(default_factory=list)
    human_review_required: bool = False
    overall_score: int = Field(..., ge=0, le=100)


class Observation(BaseModel):
    finding: str = Field(..., min_length=1, max_length=500)
    supporting_evidence: str = Field(..., min_length=1, max_length=500)
    category: ObservationCategory


class Inference(BaseModel):
    finding: str = Field(..., min_length=1, max_length=500)
    confidence: float = Field(..., ge=0.0, le=1.0)
    supporting_visual_evidence: str = Field(..., min_length=1, max_length=500)
    limitations: str = Field(..., min_length=1, max_length=500)
    category: InferenceCategory

    @field_validator('confidence')
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if v < 0 or v > 1:
            raise ValueError('Confidence must be between 0 and 1')
        return round(v, 2)


class Unknown(BaseModel):
    item: str = Field(..., min_length=1, max_length=200)
    reason: str = Field(..., min_length=1, max_length=500)
    required_evidence: str = Field(..., min_length=1, max_length=500)


class ProposedAssessment(BaseModel):
    material_family: MaterialFamily
    scrap_form: ScrapForm
    surface_condition: SurfaceCondition
    visible_contamination: VisibleContamination
    description: str = Field(..., min_length=10, max_length=1000)
    estimated_grade_hint: Optional[str] = Field(None, max_length=200)
    grade_hint_confidence: float = Field(0.0, ge=0.0, le=1.0)
    caveats: List[str] = Field(default_factory=list)


class ProcessingMetadata(BaseModel):
    model_used: str
    processing_time_ms: int
    tokens_used: int
    image_count: int
    total_image_size_bytes: int
    validation_passed: bool
    retry_count: int = 0


# --- Main Assessment Model ---

class Assessment(BaseModel):
    assessment_id: str
    evidence_quality: EvidenceQuality
    material_family: Optional[MaterialFamily] = None
    scrap_form: Optional[ScrapForm] = None
    visible_surface_condition: Optional[SurfaceCondition] = None
    visible_contamination: Optional[VisibleContamination] = None
    visual_observations: List[Observation] = Field(default_factory=list)
    observed: List[Observation] = Field(default_factory=list)
    inferred: List[Inference] = Field(default_factory=list)
    unknown: List[Unknown] = Field(default_factory=list)
    proposed_assessment: Optional[ProposedAssessment] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    missing_evidence: List[str] = Field(default_factory=list)
    recommended_next_steps: List[str] = Field(default_factory=list)
    human_review_required: bool = False
    scanner_xrf_recommended: bool = False
    processing_metadata: ProcessingMetadata
    status: AssessmentStatus = AssessmentStatus.pending
    created_at: datetime
    updated_at: datetime


# --- AI Response Schema (for structured output validation) ---

class AIAnalysisResponse(BaseModel):
    """Schema that the AI model must conform to."""
    visual_observations: List[Observation] = Field(..., min_length=1)
    inferred: List[Inference] = Field(..., min_length=1)
    unknown: List[Unknown] = Field(..., min_length=1)
    proposed_assessment: ProposedAssessment
    missing_evidence: List[str] = Field(..., min_length=1)
    recommended_next_steps: List[str] = Field(..., min_length=1)


# --- API Response Schemas ---

class AssessmentResponse(BaseModel):
    success: bool
    data: Optional[Assessment] = None
    error: Optional[str] = None
    message: Optional[str] = None


class FeedbackSubmission(BaseModel):
    reviewer_name: str = Field(..., min_length=1, max_length=100)
    corrections: dict = Field(default_factory=dict)
    confidence_override: Optional[float] = Field(None, ge=0.0, le=1.0)
    verified: bool = False


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: datetime
