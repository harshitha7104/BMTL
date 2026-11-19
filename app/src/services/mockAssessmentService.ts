// ============================================================
// Mock Assessment Service
// Simulates the backend API for the MVP frontend demo
// In production, this would make real HTTP calls to FastAPI
// ============================================================


import {
  Assessment,
  AssessmentStatus,
  MaterialFamily,
  ScrapForm,
  SurfaceCondition,
  VisibleContamination,
  UploadFile,
  FeedbackSubmission,
  FeedbackRecord,
  DashboardStats,
  ApiResponse,
  EvidenceQuality,
  ReviewTrigger,
} from '../types/assessment';
import { analyzeImageQuality, computeFileHash } from './imageAnalysis';

// In-memory storage (would be PostgreSQL/S3 in production)
const assessmentsStore: Map<string, Assessment> = new Map();

// Simulated processing delay
const PROCESSING_DELAY_MS = 2500;

/**
 * Create a new assessment from uploaded images
 */
export async function createAssessment(files: UploadFile[]): Promise<ApiResponse<Assessment>> {
  const assessmentId = `ASM-${crypto.randomUUID().slice(0, 8).toUpperCase()}`;
  const now = new Date().toISOString();

  // Create initial assessment record
  const assessment: Assessment = {
    assessment_id: assessmentId,
    schema_version: '1.0.0',
    evidence_items: [], // Will be populated during processing
    evidence_quality: {
      status: 'partially_sufficient',
      issues: [],
      recommended_additional_photos: [],
      human_review_required: false,
      overall_score: 0,
    },
    material_family: null,
    scrap_form: null,
    visible_surface_condition: null,
    visible_contamination: null,
    visual_observations: [],
    observed: [],
    inferred: [],
    unknown: [],
    proposed_assessment: null,
    confidence: 0,
    missing_evidence: [],
    recommended_next_steps: [],
    human_review_required: false,
    human_review_reasons: [],
    scanner_xrf_recommended: false,
    processing_metadata: {
      model_used: 'mock-provider (provider-independent interface)',
      processing_time_ms: 0,
      tokens_used: 0,
      image_count: files.length,
      total_image_size_bytes: files.reduce((sum, f) => sum + f.size, 0),
      validation_passed: true,
      retry_count: 0,
      provider_id: 'mock',
    },
    status: 'processing',
    created_at: now,
    updated_at: now,
  };

  assessmentsStore.set(assessmentId, assessment);

  // Simulate processing
  try {
    // Step 1: Image quality analysis
    const qualityResults: EvidenceQuality[] = [];
    for (const file of files) {
      if (file.file) {
        const { quality } = await analyzeImageQuality(file.file);
        qualityResults.push(quality);
      }
    }

    // Aggregate quality
    const avgScore = qualityResults.length > 0
      ? qualityResults.reduce((sum, q) => sum + q.overall_score, 0) / qualityResults.length
      : 50;

    const allIssues = qualityResults.flatMap(q => q.issues);

    // Determine evidence quality status
    // NOTE: We do NOT terminate on partially_sufficient — only on truly insufficient (unreadable/corrupted)
    let overallStatus: EvidenceQuality['status'] = 'sufficient';
    if (avgScore < 25) overallStatus = 'insufficient';  // Truly unreadable
    else if (avgScore < 70) overallStatus = 'partially_sufficient';  // Limited but usable

    // If evidence is truly insufficient (unreadable/corrupted), terminate early
    if (overallStatus === 'insufficient' && avgScore < 15) {
      assessment.evidence_quality = {
        status: 'insufficient',
        issues: allIssues.slice(0, 10),
        recommended_additional_photos: qualityResults[0]?.recommended_additional_photos || [],
        human_review_required: true,
        overall_score: Math.round(avgScore),
      };
      assessment.human_review_required = true;
      assessment.human_review_reasons = ['insufficient_evidence', 'low_quality_images'];
      assessment.status = 'requires_review';
      assessment.updated_at = new Date().toISOString();
      assessmentsStore.set(assessmentId, assessment);
      return { success: true, data: assessment };
    }

    assessment.evidence_quality = {
      status: overallStatus,
      issues: allIssues.slice(0, 10),
      recommended_additional_photos: qualityResults[0]?.recommended_additional_photos || [],
      human_review_required: false,  // Will be set by qualitative trigger evaluation below
      overall_score: Math.round(avgScore),
    };

    // Step 2: Simulate AI analysis (mock response)
    // NOTE: Even with partially_sufficient quality, we proceed with analysis
    // and return limited observations + unknowns + recommendations
    await simulateDelay(PROCESSING_DELAY_MS);

    const mockAnalysis = generateMockAnalysis(files, overallStatus);

    assessment.material_family = mockAnalysis.material_family;
    assessment.scrap_form = mockAnalysis.scrap_form;
    assessment.visible_surface_condition = mockAnalysis.surface_condition;
    assessment.visible_contamination = mockAnalysis.contamination;
    assessment.visual_observations = mockAnalysis.observations;
    assessment.observed = mockAnalysis.observations;
    assessment.inferred = mockAnalysis.inferences;
    assessment.unknown = mockAnalysis.unknowns;
    assessment.proposed_assessment = mockAnalysis.proposed_assessment;
    assessment.confidence = mockAnalysis.confidence;
    assessment.missing_evidence = mockAnalysis.missing_evidence;
    assessment.recommended_next_steps = mockAnalysis.recommended_next_steps;
    assessment.scanner_xrf_recommended = mockAnalysis.scanner_xrf_recommended;
    assessment.processing_metadata.processing_time_ms = PROCESSING_DELAY_MS + Math.floor(Math.random() * 1000);
    assessment.processing_metadata.tokens_used = 1500 + Math.floor(Math.random() * 2000);

    // Evaluate qualitative review triggers (revision #2)
    // Human review is triggered by qualitative conditions, NOT numeric thresholds
    const reviewReasons = evaluateReviewTriggers(
      overallStatus,
      allIssues,
      mockAnalysis,
      files.length,
    );

    assessment.human_review_required = reviewReasons.length > 0;
    assessment.human_review_reasons = reviewReasons;
    assessment.status = reviewReasons.length > 0 ? 'requires_review' : 'completed';
    assessment.updated_at = new Date().toISOString();

    assessmentsStore.set(assessmentId, assessment);

    return { success: true, data: assessment };
  } catch (error) {
    assessment.status = 'failed';
    assessment.updated_at = new Date().toISOString();
    assessmentsStore.set(assessmentId, assessment);

    return {
      success: false,
      error: 'Assessment processing failed. Please try again.',
    };
  }
}

/**
 * Get an assessment by ID
 */
export async function getAssessment(assessmentId: string): Promise<ApiResponse<Assessment>> {
  const assessment = assessmentsStore.get(assessmentId);
  if (!assessment) {
    return { success: false, error: 'Assessment not found' };
  }
  return { success: true, data: assessment };
}

/**
 * Submit feedback for an assessment
 */
export async function submitFeedback(feedback: FeedbackSubmission): Promise<ApiResponse<FeedbackRecord>> {
  const assessment = assessmentsStore.get(feedback.assessment_id);
  if (!assessment) {
    return { success: false, error: 'Assessment not found' };
  }

  // Store feedback separately (in production, this would be a separate table)
  assessment.status = 'completed';
  assessment.updated_at = new Date().toISOString();
  assessmentsStore.set(feedback.assessment_id, assessment);

  // Create a feedback record
  const feedbackRecord: FeedbackRecord = {
    feedback_id: `FB-${Math.random().toString(36).substring(2, 8).toUpperCase()}`,
    assessment_id: feedback.assessment_id,
    reviewer_name: feedback.reviewer_name,
    feedback_category: feedback.feedback_category || 'correction',
    corrections: feedback.corrections,
    confidence_override: feedback.confidence_override,
    verified: feedback.verified,
    verification_status: 'unverified',
    submitted_at: feedback.submitted_at,
  };

  return { success: true, data: feedbackRecord };
}

/**
 * Get dashboard statistics
 */
export async function getDashboardStats(): Promise<ApiResponse<DashboardStats>> {
  const all = Array.from(assessmentsStore.values());
  const stats: DashboardStats = {
    total_assessments: all.length,
    completed: all.filter(a => a.status === 'completed').length,
    pending_review: all.filter(a => a.status === 'requires_review').length,
    failed: all.filter(a => a.status === 'failed').length,
    avg_confidence: all.length > 0
      ? all.reduce((sum, a) => sum + a.confidence, 0) / all.length
      : 0,
  };
  return { success: true, data: stats };
}

/**
 * Get all assessments (for dashboard)
 */
export async function getAllAssessments(): Promise<ApiResponse<Assessment[]>> {
  const all = Array.from(assessmentsStore.values());
  // Sort by created_at descending
  all.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  return { success: true, data: all };
}

/**
 * Health check
 */
export async function healthCheck(): Promise<ApiResponse<{ status: string; version: string }>> {
  return {
    success: true,
    data: { status: 'healthy', version: '1.0.0-mvp' },
  };
}

// ============================================================
// Mock AI Analysis Generator
// Simulates structured AI responses with proper uncertainty
// ============================================================

/**
 * Evaluate qualitative review triggers.
 *
 * Human review is triggered by qualitative conditions, NOT by numeric confidence
 * thresholds. This implements revision #2 of the architecture.
 *
 * Triggers:
 * - insufficient_evidence: Image quality too poor for reliable analysis
 * - high_uncertainty: Multiple conflicting inferences or very low confidence
 * - conflicting_images: (would require multi-image comparison in production)
 * - consequential_claim: Grade/composition claimed without physical verification
 * - unsupported_conclusion: Inference lacks adequate visual evidence
 * - hazardous_material: Potential safety risk identified
 * - mixed_material: Cannot separate components visually
 * - electronic_scrap: Requires specialized e-waste handling
 * - low_quality_images: Image quality below analysis threshold
 * - model_refusal: AI model refused to analyze
 * - schema_validation_failure: AI response didn't match expected schema
 * - processing_error: Technical error during analysis
 */
function evaluateReviewTriggers(
  qualityStatus: EvidenceQuality['status'],
  qualityIssues: { severity: string }[],
  analysis: ReturnType<typeof generateMockAnalysis>,
  imageCount: number,
): ReviewTrigger[] {
  const triggers: ReviewTrigger[] = [];

  // 1. Insufficient evidence — quality too poor
  if (qualityStatus === 'insufficient') {
    triggers.push('insufficient_evidence');
  }

  // 2. Low quality images — significant quality issues detected
  if (qualityStatus === 'partially_sufficient') {
    const hasHighSeverity = qualityIssues.some(
      (i) => i.severity === 'high' || i.severity === 'critical'
    );
    if (hasHighSeverity) {
      triggers.push('low_quality_images');
    }
  }

  // 3. High uncertainty — multiple inferences with low confidence
  const lowConfidenceInferences = analysis.inferences.filter(
    (inf: { confidence: number }) => inf.confidence < 0.4
  );
  if (lowConfidenceInferences.length >= 2) {
    triggers.push('high_uncertainty');
  }

  // 4. Unsupported conclusion — inference without strong visual evidence
  const unsupportedInferences = analysis.inferences.filter(
    (inf: { confidence: number }) => inf.confidence < 0.35
  );
  if (unsupportedInferences.length > 0) {
    triggers.push('unsupported_conclusion');
  }

  // 5. Consequential claim — grade hint provided (even with low confidence)
  if (
    analysis.proposed_assessment?.estimated_grade_hint &&
    analysis.proposed_assessment.grade_hint_confidence > 0
  ) {
    triggers.push('consequential_claim');
  }

  // 6. Hazardous material — material family is hazardous
  if (analysis.material_family === 'hazardous') {
    triggers.push('hazardous_material');
  }

  // 7. Mixed material — cannot separate components visually
  if (analysis.material_family === 'mixed') {
    triggers.push('mixed_material');
  }

  // 8. Electronic scrap — requires specialized handling
  if (analysis.material_family === 'electronic') {
    triggers.push('electronic_scrap');
  }

  // 9. Single image with complex material — insufficient angles
  if (imageCount === 1 && analysis.unknowns.length > 3) {
    // Would be 'conflicting_images' if multiple images contradicted
    // For single image, we flag high uncertainty instead (already covered above)
  }

  return triggers;
}

function generateMockAnalysis(files: UploadFile[], qualityStatus: string) {
  // Randomly select a realistic scenario
  const scenarios = [
    generateFerrousScenario,
    generateNonFerrousScenario,
    generateMixedScenario,
    generateElectronicScenario,
  ];

  const scenarioIdx = Math.floor(Math.random() * scenarios.length);
  return scenarios[scenarioIdx](qualityStatus);
}

function generateFerrousScenario(qualityStatus: string) {
  const confidence = qualityStatus === 'sufficient' ? 0.72 : 0.45;
  return {
    material_family: 'ferrous' as MaterialFamily,
    scrap_form: 'irregular' as ScrapForm,
    surface_condition: 'heavily_rusted' as SurfaceCondition,
    contamination: 'dirt_soil' as VisibleContamination,
    observations: [
      {
        finding: 'Dark brown-orange surface discoloration consistent with iron oxide formation',
        supporting_evidence: 'Uniform rust coloring visible across approximately 80% of visible surface area',
        category: 'surface' as const,
      },
      {
        finding: 'Irregular, non-uniform geometry with visible edges and corners',
        supporting_evidence: 'Angular shapes visible suggesting cut or broken structural material',
        category: 'shape' as const,
      },
      {
        finding: 'Dark particulate matter visible in surface crevices',
        supporting_evidence: 'Darker deposits in textured areas consistent with soil or environmental contamination',
        category: 'contamination' as const,
      },
      {
        finding: 'Metallic luster visible in areas where surface rust has been disturbed',
        supporting_evidence: 'Small bright areas visible suggesting underlying metallic substrate',
        category: 'color' as const,
      },
    ],
    inferences: [
      {
        finding: 'Material is likely a ferrous (iron-based) alloy',
        confidence: confidence,
        supporting_visual_evidence: 'Rust pattern and color are characteristic of iron oxidation. Metallic substrate visible in disturbed areas.',
        limitations: 'Visual appearance alone cannot distinguish between carbon steel, cast iron, or specific steel alloys. XRF analysis required for grade identification.',
        category: 'material_family' as const,
      },
      {
        finding: 'Heavy surface rust suggests prolonged outdoor exposure',
        confidence: 0.65,
        supporting_visual_evidence: 'Thick, flaking rust pattern with deep orange-brown coloration',
        limitations: 'Rust thickness does not directly correlate with exposure duration. Internal material condition cannot be assessed visually.',
        category: 'condition' as const,
      },
      {
        finding: 'Material may be structural steel or heavy plate based on thickness visible at edges',
        confidence: 0.4,
        supporting_visual_evidence: 'Edge profile suggests material thickness of 5-15mm range',
        limitations: 'Cannot determine exact thickness, grade, or original application from visual inspection alone.',
        category: 'scrap_form' as const,
      },
    ],
    unknowns: [
      {
        item: 'Exact alloy composition and grade',
        reason: 'Chemical composition cannot be determined from visual inspection',
        required_evidence: 'XRF spectroscopy or laboratory chemical analysis',
      },
      {
        item: 'Internal material condition',
        reason: 'Surface rust may mask internal corrosion, cracking, or contamination',
        required_evidence: 'Cross-section inspection or ultrasonic testing',
      },
      {
        item: 'Exact weight and dimensions',
        reason: 'Scale reference not provided in image',
        required_evidence: 'Physical measurement with calibrated scale',
      },
      {
        item: 'Presence of hazardous coatings (lead paint, asbestos insulation)',
        reason: 'Cannot identify coating composition visually',
        required_evidence: 'Laboratory coating analysis',
      },
      {
        item: 'Magnetic properties',
        reason: 'Cannot assess magnetism from still image',
        required_evidence: 'Physical magnetic test',
      },
    ],
    proposed_assessment: {
      material_family: 'ferrous' as MaterialFamily,
      scrap_form: 'irregular' as ScrapForm,
      surface_condition: 'heavily_rusted' as SurfaceCondition,
      visible_contamination: 'dirt_soil' as VisibleContamination,
      description: 'Ferrous scrap material with heavy surface oxidation. Irregular geometry suggests cut or broken structural component. Visible surface contamination includes soil/dirt deposits.',
      estimated_grade_hint: 'Possibly carbon steel (unverified)',
      grade_hint_confidence: 0.35,
      caveats: [
        'Material grade cannot be confirmed without spectroscopic analysis',
        'Surface rust may significantly reduce visible metal recovery',
        'Contamination level requires physical assessment',
        'Hazardous coating presence cannot be ruled out',
      ],
    },
    confidence,
    missing_evidence: [
      'Close-up photograph of material cross-section or edge',
      'Photograph with scale reference (ruler or coin)',
      'Multiple angle photographs showing full geometry',
      'Photograph of any markings, stamps, or labels on material',
    ],
    recommended_next_steps: [
      'Perform XRF analysis to determine alloy composition',
      'Conduct physical inspection for internal corrosion',
      'Test for hazardous coatings before processing',
      'Weigh and measure material for volume estimation',
      'Check for magnetic response to confirm ferrous classification',
    ],
    human_review_required: qualityStatus !== 'sufficient',
    scanner_xrf_recommended: true,
  };
}

function generateNonFerrousScenario(qualityStatus: string) {
  const confidence = qualityStatus === 'sufficient' ? 0.68 : 0.42;
  return {
    material_family: 'non_ferrous' as MaterialFamily,
    scrap_form: 'irregular' as ScrapForm,
    surface_condition: 'oxidized' as SurfaceCondition,
    contamination: 'none_visible' as VisibleContamination,
    observations: [
      {
        finding: 'Yellowish-golden metallic surface with green patina in recessed areas',
        supporting_evidence: 'Color characteristics visible across the majority of the surface',
        category: 'color' as const,
      },
      {
        finding: 'Smooth metallic texture with areas of surface roughness',
        supporting_evidence: 'Reflective areas contrast with matte oxidized regions',
        category: 'texture' as const,
      },
      {
        finding: 'Green-blue discoloration in crevices and joints',
        supporting_evidence: 'Characteristic verdigris pattern visible in sheltered areas',
        category: 'surface' as const,
      },
    ],
    inferences: [
      {
        finding: 'Material is likely a copper or copper alloy (brass/bronze)',
        confidence: confidence,
        supporting_visual_evidence: 'Golden-yellow base color with green patina is characteristic of copper alloys',
        limitations: 'Cannot distinguish between pure copper, brass (copper-zinc), or bronze (copper-tin) from appearance alone. Specific alloy grade requires spectroscopic analysis.',
        category: 'material_family' as const,
      },
      {
        finding: 'Surface oxidation suggests environmental exposure',
        confidence: 0.7,
        supporting_visual_evidence: 'Verdigris (green patina) formation indicates copper oxidation over time',
        limitations: 'Patina development rate varies with environment. Cannot determine age or exposure conditions.',
        category: 'condition' as const,
      },
    ],
    unknowns: [
      {
        item: 'Specific copper alloy type (pure copper vs brass vs bronze)',
        reason: 'Visual color alone cannot reliably distinguish copper alloys',
        required_evidence: 'XRF analysis or density measurement',
      },
      {
        item: 'Alloy grade and purity percentage',
        reason: 'Composition cannot be determined visually',
        required_evidence: 'Spectroscopic analysis (XRF or OES)',
      },
      {
        item: 'Internal soundness',
        reason: 'Surface appearance does not reveal internal defects',
        required_evidence: 'Physical inspection, ultrasonic testing',
      },
      {
        item: 'Weight and exact dimensions',
        reason: 'No scale reference in image',
        required_evidence: 'Physical measurement',
      },
    ],
    proposed_assessment: {
      material_family: 'non_ferrous' as MaterialFamily,
      scrap_form: 'irregular' as ScrapForm,
      surface_condition: 'oxidized' as SurfaceCondition,
      visible_contamination: 'none_visible' as VisibleContamination,
      description: 'Non-ferrous metallic scrap with characteristics consistent with copper or copper alloy. Surface shows oxidation with green patina in recessed areas. No visible surface contamination.',
      estimated_grade_hint: 'Possibly copper alloy (unverified)',
      grade_hint_confidence: 0.3,
      caveats: [
        'Cannot distinguish between copper, brass, and bronze visually',
        'Alloy composition requires spectroscopic verification',
        'Surface oxidation may represent material loss',
        'Market value depends on exact alloy determination',
      ],
    },
    confidence,
    missing_evidence: [
      'Close-up photograph showing surface color under neutral lighting',
      'Photograph with scale reference',
      'Photograph of any markings or stamps',
      'Cross-section photograph if material can be safely sectioned',
    ],
    recommended_next_steps: [
      'Perform XRF analysis to determine exact alloy composition',
      'Conduct density test as preliminary alloy indicator',
      'Check for solder joints or mixed-material attachments',
      'Separate by visual sub-classification before processing',
    ],
    human_review_required: qualityStatus !== 'sufficient',
    scanner_xrf_recommended: true,
  };
}

function generateMixedScenario(qualityStatus: string) {
  const confidence = qualityStatus === 'sufficient' ? 0.55 : 0.35;
  return {
    material_family: 'mixed' as MaterialFamily,
    scrap_form: 'irregular' as ScrapForm,
    surface_condition: 'contaminated' as SurfaceCondition,
    contamination: 'plastic' as VisibleContamination,
    observations: [
      {
        finding: 'Multiple distinct material types visible in the image',
        supporting_evidence: 'Areas of different color, texture, and reflectivity suggest heterogeneous composition',
        category: 'other' as const,
      },
      {
        finding: 'Metallic surfaces interspersed with non-metallic materials',
        supporting_evidence: 'Contrasting reflective metal areas with dark non-reflective regions',
        category: 'surface' as const,
      },
      {
        finding: 'Possible plastic or rubber components attached to metal',
        supporting_evidence: 'Dark flexible-looking material visible at edges and connections',
        category: 'contamination' as const,
      },
    ],
    inferences: [
      {
        finding: 'Material is a mixed/composite scrap containing multiple material types',
        confidence: confidence,
        supporting_visual_evidence: 'Visual heterogeneity with distinct metallic and non-metallic zones',
        limitations: 'Cannot identify all material components or their proportions from visual inspection. Each component requires separate assessment.',
        category: 'material_family' as const,
      },
      {
        finding: 'Material may require separation before recycling',
        confidence: 0.6,
        supporting_visual_evidence: 'Visible attachment of dissimilar materials suggests composite construction',
        limitations: 'Separation difficulty and economic viability depend on material proportions and attachment methods.',
        category: 'other' as const,
      },
    ],
    unknowns: [
      {
        item: 'Exact material composition and proportions',
        reason: 'Multiple materials present; cannot quantify from image',
        required_evidence: 'Physical separation and individual material identification',
      },
      {
        item: 'Presence of hazardous materials',
        reason: 'Mixed scrap may contain hazardous components not visually identifiable',
        required_evidence: 'Laboratory testing of each material component',
      },
      {
        item: 'Separation feasibility and cost',
        reason: 'Requires physical assessment of attachment methods',
        required_evidence: 'Hands-on inspection and separation testing',
      },
      {
        item: 'Individual material grades',
        reason: 'Each component requires separate analysis',
        required_evidence: 'XRF analysis of separated components',
      },
    ],
    proposed_assessment: {
      material_family: 'mixed' as MaterialFamily,
      scrap_form: 'irregular' as ScrapForm,
      surface_condition: 'contaminated' as SurfaceCondition,
      visible_contamination: 'plastic' as VisibleContamination,
      description: 'Mixed material scrap containing both metallic and non-metallic components. Visible plastic/rubber attachments to metal surfaces. Material requires separation before individual assessment.',
      estimated_grade_hint: null,
      grade_hint_confidence: 0,
      caveats: [
        'Mixed scrap has significantly lower value than sorted materials',
        'Cannot determine material proportions visually',
        'Hazardous material presence cannot be ruled out',
        'Separation costs may exceed material value',
        'Individual component assessment required for accurate valuation',
      ],
    },
    confidence,
    missing_evidence: [
      'Individual close-up photographs of each distinct material type',
      'Photograph showing overall composition and proportions',
      'Photograph with scale reference',
      'Photograph of any labels, markings, or identifying features',
    ],
    recommended_next_steps: [
      'Physically separate material types for individual assessment',
      'Screen for hazardous materials before processing',
      'Assess each separated component individually',
      'Evaluate separation cost vs. recovered material value',
      'Consider professional scrap sorting service for large quantities',
    ],
    human_review_required: true,
    scanner_xrf_recommended: true,
  };
}

function generateElectronicScenario(qualityStatus: string) {
  const confidence = qualityStatus === 'sufficient' ? 0.6 : 0.38;
  return {
    material_family: 'electronic' as MaterialFamily,
    scrap_form: 'electronic_component' as ScrapForm,
    surface_condition: 'clean' as SurfaceCondition,
    contamination: 'none_visible' as VisibleContamination,
    observations: [
      {
        finding: 'Green circuit board substrate visible',
        supporting_evidence: 'Characteristic FR-4 green PCB material visible in multiple areas',
        category: 'color' as const,
      },
      {
        finding: 'Metallic components and connectors visible on board',
        supporting_evidence: 'Silver and gold-colored components visible on substrate',
        category: 'surface' as const,
      },
      {
        finding: 'Integrated circuits and passive components mounted on board',
        supporting_evidence: 'Rectangular black IC packages and small cylindrical components visible',
        category: 'shape' as const,
      },
    ],
    inferences: [
      {
        finding: 'Material is electronic scrap (e-waste) containing a printed circuit board',
        confidence: confidence,
        supporting_visual_evidence: 'Green PCB substrate with mounted electronic components is distinctive',
        limitations: 'Cannot determine board classification (consumer, industrial, telecommunications) or precious metal content from visual inspection alone.',
        category: 'material_family' as const,
      },
      {
        finding: 'Board may contain recoverable precious metals',
        confidence: 0.5,
        supporting_visual_evidence: 'Gold-colored connectors and silver-colored solder joints visible',
        limitations: 'Precious metal content varies dramatically by board type and age. Exact content requires assay. Cannot provide value estimate without board classification.',
        category: 'other' as const,
      },
    ],
    unknowns: [
      {
        item: 'Precious metal content (gold, silver, palladium)',
        reason: 'Cannot quantify metal content from visual inspection',
        required_evidence: 'Assay or certified e-waste recycling analysis',
      },
      {
        item: 'Board classification and grade',
        reason: 'Cannot determine if board is high-grade (telecom) or low-grade (consumer)',
        required_evidence: 'Component identification and board origin assessment',
      },
      {
        item: 'Presence of hazardous substances (lead solder, cadmium, beryllium)',
        reason: 'Cannot identify hazardous materials visually',
        required_evidence: 'XRF testing for RoHS compliance',
      },
      {
        item: 'Data storage components with potential data',
        reason: 'Memory chips may contain recoverable data requiring secure handling',
        required_evidence: 'Component identification and data destruction certification',
      },
    ],
    proposed_assessment: {
      material_family: 'electronic' as MaterialFamily,
      scrap_form: 'electronic_component' as ScrapForm,
      surface_condition: 'clean' as SurfaceCondition,
      visible_contamination: 'none_visible' as VisibleContamination,
      description: 'Electronic scrap containing printed circuit board with mounted components. Visible IC packages, passive components, and metallic connectors. Board appears to be in reasonable condition.',
      estimated_grade_hint: null,
      grade_hint_confidence: 0,
      caveats: [
        'Precious metal content cannot be estimated from appearance',
        'Hazardous material testing required before processing',
        'Data security assessment needed for memory components',
        'Board grade significantly affects value - requires expert classification',
        'Environmental regulations may apply to e-waste processing',
      ],
    },
    confidence,
    missing_evidence: [
      'Close-up photograph of connectors and edge fingers',
      'Photograph showing board markings and manufacturer codes',
      'Photograph of component side at higher magnification',
      'Overall photograph showing board dimensions with scale reference',
    ],
    recommended_next_steps: [
      'Classify board grade with e-waste specialist',
      'Test for hazardous substances (RoHS screening)',
      'Assess data security requirements for memory components',
      'Obtain assay for precious metal content estimation',
      'Verify compliance with local e-waste regulations',
    ],
    human_review_required: true,
    scanner_xrf_recommended: true,
  };
}

function simulateDelay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
