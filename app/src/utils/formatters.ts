// ============================================================
// Shared Formatting Utilities
// ============================================================

/**
 * Converts snake_case enum values to human-readable Title Case.
 * Example: "heavily_rusted" → "Heavily Rusted"
 */
export function formatEnum(value: string): string {
  return value
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Formats a confidence value (0-1) as a percentage string.
 * Example: 0.72 → "72%"
 */
export function formatConfidence(confidence: number): string {
  return `${Math.round(confidence * 100)}%`;
}

/**
 * Returns a Tailwind color class based on confidence level.
 */
export function getConfidenceColor(confidence: number): string {
  if (confidence >= 0.7) return 'text-emerald-600';
  if (confidence >= 0.4) return 'text-amber-600';
  return 'text-red-600';
}

/**
 * Returns a Tailwind background color class for confidence bars.
 */
export function getConfidenceBarColor(confidence: number): string {
  if (confidence >= 0.7) return 'bg-emerald-500';
  if (confidence >= 0.4) return 'bg-amber-500';
  return 'bg-red-500';
}

/**
 * Formats a byte count into a human-readable size string.
 */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Formats an ISO date string into a locale-appropriate display string.
 */
export function formatDate(isoString: string): string {
  return new Date(isoString).toLocaleString();
}

/**
 * Returns a human-readable label for a ReviewTrigger value.
 */
export function formatReviewTrigger(trigger: string): string {
  const labels: Record<string, string> = {
    insufficient_evidence: 'Insufficient Evidence',
    high_uncertainty: 'High Uncertainty',
    conflicting_images: 'Conflicting Images',
    consequential_claim: 'Unverified Consequential Claim',
    unsupported_conclusion: 'Unsupported Conclusion',
    hazardous_material: 'Potential Hazardous Material',
    mixed_material: 'Mixed Material — Cannot Separate',
    electronic_scrap: 'Electronic Scrap — Specialized Handling',
    low_quality_images: 'Low Quality Images',
    model_refusal: 'AI Model Refusal',
    schema_validation_failure: 'Schema Validation Failure',
    processing_error: 'Processing Error',
  };
  return labels[trigger] || trigger.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}
