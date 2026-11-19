// ============================================================
// Scrap Assessment System - Type Definitions
// Mirrors the Pydantic schemas from the backend
// ============================================================

// --- Evidence Quality ---

export type EvidenceQualityStatus = 'sufficient' | 'partially_sufficient' | 'insufficient';

export interface QualityIssue {
  issue: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  description: string;
}

export interface EvidenceQuality {
  status: EvidenceQualityStatus;
  issues: QualityIssue[];
  recommended_additional_photos: string[];
  human_review_required: boolean;
  overall_score: number; // 0-100
}

// --- Visual Observations ---

export interface Observation {
  finding: string;
  supporting_evidence: string;
  category: 'surface' | 'shape' | 'color' | 'texture' | 'contamination' | 'other';
}

// --- Inferences ---

export interface Inference {
  finding: string;
  confidence: number; // 0.0 - 1.0
  supporting_visual_evidence: string;
  limitations: string;
  category: 'material_family' | 'scrap_form' | 'condition' | 'contamination' | 'other';
}

// --- Unknowns ---

export interface Unknown {
  item: string;
  reason: string;
  required_evidence: string;
}

// --- Material Assessment ---

export type MaterialFamily =
  | 'ferrous'
  | 'non_ferrous'
  | 'mixed'
  | 'electronic'
  | 'plastic'
  | 'organic'
  | 'hazardous'
  | 'unidentifiable';

export type ScrapForm =
  | 'sheet'
  | 'bar'
  | 'pipe'
  | 'wire'
  | 'turning'
  | 'casting'
  | 'forging'
  | 'machined_part'
  | 'electronic_component'
  | 'fragment'
  | 'irregular'
  | 'unidentifiable';

export type SurfaceCondition =
  | 'clean'
  | 'lightly_rusted'
  | 'heavily_rusted'
  | 'painted'
  | 'coated'
  | 'oxidized'
  | 'contaminated'
  | 'corroded'
  | 'unidentifiable';

export type VisibleContamination =
  | 'none_visible'
  | 'oil_grease'
  | 'dirt_soil'
  | 'paint'
  | 'rubber'
  | 'plastic'
  | 'concrete'
  | 'organic'
  | 'chemical_residue'
  | 'unknown';

// --- Proposed Assessment ---

export interface ProposedAssessment {
  material_family: MaterialFamily;
  scrap_form: ScrapForm;
  surface_condition: SurfaceCondition;
  visible_contamination: VisibleContamination;
  description: string;
  estimated_grade_hint: string | null;
  grade_hint_confidence: number;
  caveats: string[];
}

// --- Processing Metadata ---

export interface ProcessingMetadata {
  model_used: string;
  processing_time_ms: number;
  tokens_used: number;
  image_count: number;
  total_image_size_bytes: number;
  validation_passed: boolean;
  retry_count: number;
  provider_id: string; // Added to match backend schema
}

// --- Evidence Item (Per-Image Metadata) ---

export interface EvidenceItem {
  evidence_id: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  hash_sha256: string;
  width: number | null;
  height: number | null;
  quality_status: EvidenceQualityStatus;
  quality_score: number; // 0-100
  quality_issues: QualityIssue[];
}

// --- Human Review Triggers (Qualitative, not numeric) ---

export type ReviewTrigger =
  | 'insufficient_evidence'       // Image quality too poor for reliable analysis
  | 'high_uncertainty'            // Multiple conflicting inferences
  | 'conflicting_images'          // Uploaded images contradict each other
  | 'consequential_claim'         // Grade/composition claimed without physical verification
  | 'unsupported_conclusion'      // Inference lacks adequate visual evidence
  | 'hazardous_material'          // Potential safety risk identified
  | 'mixed_material'              // Cannot separate components visually
  | 'electronic_scrap'            // Requires specialized e-waste handling
  | 'low_quality_images'          // Image quality below analysis threshold
  | 'model_refusal'               // AI model refused to analyze (safety/policy)
  | 'schema_validation_failure'   // AI response didn't match expected schema
  | 'processing_error';           // Technical error during analysis

// --- Full Assessment ---

export type AssessmentStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'requires_review';

// Schema version for migration tracking
export const SCHEMA_VERSION = '1.0.0';

export interface Assessment {
  assessment_id: string;
  schema_version: string; // Added for schema migration tracking
  evidence_quality: EvidenceQuality;
  evidence_items: EvidenceItem[]; // Added per-image evidence records
  material_family: MaterialFamily | null;
  scrap_form: ScrapForm | null;
  visible_surface_condition: SurfaceCondition | null;
  visible_contamination: VisibleContamination | null;
  visual_observations: Observation[];
  observed: Observation[];
  inferred: Inference[];
  unknown: Unknown[];
  proposed_assessment: ProposedAssessment | null;
  confidence: number;
  missing_evidence: string[];
  recommended_next_steps: string[];
  human_review_required: boolean;
  human_review_reasons: ReviewTrigger[];
  scanner_xrf_recommended: boolean;
  processing_metadata: ProcessingMetadata;
  status: AssessmentStatus;
  created_at: string;
  updated_at: string;
}

// --- Upload ---

export interface UploadFile {
  id: string;
  file: File;
  preview: string;
  name: string;
  size: number;
  type: string;
  hash?: string;
  validation_status: 'pending' | 'valid' | 'invalid' | 'processing';
  validation_error?: string;
}

// --- Feedback (Stored SEPARATELY from AI output — never auto-retrains) ---

export type VerificationStatus = 'unverified' | 'partially_verified' | 'verified';

export type FeedbackCategory = 
  | 'correction'          // Factual correction to AI output
  | 'clarification'       // Additional context or explanation
  | 'disagreement'        // Disagrees with AI assessment
  | 'confirmation'        // Confirms AI assessment is correct
  | 'additional_info'     // Provides new information
  | 'other';

export interface FeedbackSubmission {
  assessment_id: string;
  reviewer_name: string;
  feedback_category: FeedbackCategory; // Added feedback category
  corrections: {
    material_family?: MaterialFamily;
    scrap_form?: ScrapForm;
    surface_condition?: SurfaceCondition;
    contamination?: VisibleContamination;
    additional_notes?: string;
  };
  confidence_override?: number;
  verified: boolean;
  submitted_at: string;
}

/**
 * FeedbackRecord — stored separately from the original AI assessment.
 * The original AI output is NEVER modified. Feedback is an independent record.
 * No automatic retraining uses unverified feedback.
 */
export interface FeedbackRecord {
  feedback_id: string;
  assessment_id: string;
  reviewer_name: string;
  feedback_category: FeedbackCategory; // Added feedback category
  corrections: FeedbackSubmission['corrections'];
  confidence_override?: number;
  verified: boolean;
  verification_status: VerificationStatus;
  submitted_at: string;
  // Original AI output is preserved separately and never overwritten
}

// --- API Response ---

export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
}

// --- Health Response ---

export interface HealthResponse {
  status: string;
  version: string;
  ai_provider: string;
  timestamp: string;
}

// --- Dashboard Stats ---

export interface DashboardStats {
  total_assessments: number;
  completed: number;
  pending_review: number;
  failed: number;
  avg_confidence: number;
}
