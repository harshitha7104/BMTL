// ============================================================
// Provider-Independent AI Interface
// ============================================================
//
// This module defines the abstract interface for AI analysis providers.
// The system does NOT depend on any specific AI provider.
//
// Current implementations:
//   - MockProvider (src/services/mockAssessmentService.ts) — for development/demo
//
// Future implementations (optional, requires budget/hardware):
//   - OpenAIProvider — uses OpenAI Responses API with Structured Outputs
//   - LocalVisionProvider — uses a local vision model (requires hardware check)
//
// CONSTRAINTS:
//   - No paid API calls during development or testing
//   - OpenAI integration is OPTIONAL
//   - No large local model downloads without hardware verification
//   - Mock provider is the DEFAULT and fully functional
// ============================================================

import {
  Observation,
  Inference,
  Unknown,
  ProposedAssessment,
  ReviewTrigger,
} from '../types/assessment';

// --- AI Provider Configuration ---

export interface AIProviderConfig {
  /** Provider identifier (e.g., 'mock', 'openai', 'local') */
  providerId: string;
  /** Model name/identifier (provider-specific) */
  modelId: string;
  /** Whether this provider requires paid API access */
  requiresApiKey: boolean;
  /** Whether this provider requires local hardware (GPU, etc.) */
  requiresLocalHardware: boolean;
  /** Maximum number of images per request */
  maxImages: number;
  /** Maximum file size per image in bytes */
  maxFileSizeBytes: number;
  /** Request timeout in milliseconds */
  timeoutMs: number;
  /** Maximum retry attempts for transient failures */
  maxRetries: number;
}

// --- AI Analysis Input ---

export interface AIAnalysisInput {
  /** Base64-encoded images or File objects (provider decides format) */
  images: Array<{
    data: string; // base64 encoded
    mimeType: string;
    filename: string;
  }>;
  /** Context from image quality analysis */
  qualityContext?: {
    overallStatus: 'sufficient' | 'partially_sufficient' | 'insufficient';
    issues: string[];
    recommendations: string[];
  };
}

// --- AI Analysis Output (Structured, Schema-Validated) ---

export interface AIAnalysisOutput {
  /** Directly visible characteristics */
  observations: Observation[];
  /** Tentative interpretations with confidence and limitations */
  inferences: Inference[];
  /** Items that cannot be determined from available evidence */
  unknowns: Unknown[];
  /** Overall material classification (tentative) */
  proposedAssessment: ProposedAssessment;
  /** What additional evidence is needed */
  missingEvidence: string[];
  /** Recommended physical tests and actions */
  recommendedNextSteps: string[];
  /** Overall confidence in the assessment (0-1) */
  confidence: number;
  /** Whether XRF spectroscopy is recommended */
  scannerXrfRecommended: boolean;
  /** Material family classification */
  materialFamily: ProposedAssessment['material_family'];
  /** Scrap form classification */
  scrapForm: ProposedAssessment['scrap_form'];
  /** Surface condition */
  surfaceCondition: ProposedAssessment['surface_condition'];
  /** Visible contamination */
  contamination: ProposedAssessment['visible_contamination'];
}

// --- AI Provider Response ---

export interface AIProviderResponse {
  /** Whether the analysis succeeded */
  success: boolean;
  /** Analysis output (if successful) */
  output?: AIAnalysisOutput;
  /** Error message (if failed) */
  error?: string;
  /** Error category for programmatic handling */
  errorType?: AIErrorType;
  /** Qualitative review triggers identified during analysis */
  reviewTriggers: ReviewTrigger[];
  /** Processing metadata */
  metadata: {
    providerId: string;
    modelId: string;
    processingTimeMs: number;
    tokensUsed?: number;
    retryCount: number;
  };
}

// --- Error Types ---

export type AIErrorType =
  | 'provider_unavailable'     // AI service is down
  | 'authentication_error'     // Invalid API key
  | 'rate_limit_exceeded'      // Too many requests
  | 'timeout'                  // Request took too long
  | 'model_refusal'            // Model refused (safety/policy)
  | 'schema_validation_failure' // Response didn't match expected schema
  | 'invalid_input'            // Input validation failed
  | 'image_too_large'          // Image exceeds size limit
  | 'too_many_images'          // Exceeds max image count
  | 'processing_error'         // Generic processing failure
  | 'not_implemented';         // Provider not yet implemented

// --- AI Provider Interface ---

/**
 * Abstract interface for AI analysis providers.
 *
 * All providers MUST:
 * 1. Return structured output matching AIAnalysisOutput
 * 2. Never claim exact chemical composition from appearance
 * 3. Never claim specific alloy grade without verification
 * 4. Always separate observations from inferences from unknowns
 * 5. Include confidence levels and limitations for every inference
 * 6. Identify review triggers when appropriate
 *
 * Providers MUST NOT:
 * - Make paid API calls without explicit user configuration
 * - Download large models without hardware verification
 * - Return unvalidated free-form output
 */
export interface IAIProvider {
  /** Provider configuration */
  readonly config: AIProviderConfig;

  /**
   * Analyze images and return structured assessment.
   *
   * The provider MUST validate its output against the AIAnalysisOutput schema
   * before returning. Invalid output should result in a schema_validation_failure error.
   */
  analyze(input: AIAnalysisInput): Promise<AIProviderResponse>;

  /**
   * Check if the provider is available and properly configured.
   * Used for health checks and startup validation.
   */
  isAvailable(): Promise<boolean>;

  /**
   * Get provider display name for UI display.
   */
  getDisplayName(): string;
}

// --- Provider Registry ---

/**
 * Registry of available AI providers.
 * The system selects the first available provider in priority order.
 *
 * Default priority:
 * 1. MockProvider (always available, no cost)
 * 2. OpenAIProvider (if API key configured)
 * 3. LocalVisionProvider (if hardware available)
 */
export class AIProviderRegistry {
  private providers: Map<string, IAIProvider> = new Map();
  private priority: string[] = [];

  register(provider: IAIProvider, priority?: number): void {
    this.providers.set(provider.config.providerId, provider);
    if (priority !== undefined) {
      this.priority[priority] = provider.config.providerId;
    } else {
      this.priority.push(provider.config.providerId);
    }
  }

  async getActiveProvider(): Promise<IAIProvider | null> {
    for (const providerId of this.priority) {
      const provider = this.providers.get(providerId);
      if (provider && (await provider.isAvailable())) {
        return provider;
      }
    }
    return null;
  }

  getProvider(providerId: string): IAIProvider | undefined {
    return this.providers.get(providerId);
  }

  listProviders(): Array<{ id: string; name: string; available: boolean }> {
    return Array.from(this.providers.values()).map((p) => ({
      id: p.config.providerId,
      name: p.getDisplayName(),
      available: false, // Would check async in production
    }));
  }
}

// --- Default Provider Selection ---

/**
 * Get the default AI provider for the current environment.
 *
 * In development/demo: Returns MockProvider (no API key needed)
 * In production with OpenAI: Would return OpenAIProvider if configured
 *
 * This function ensures the system ALWAYS works without paid API access.
 */
export function getDefaultProviderConfig(): AIProviderConfig {
  return {
    providerId: 'mock',
    modelId: 'mock-scrap-assessment-v1',
    requiresApiKey: false,
    requiresLocalHardware: false,
    maxImages: 5,
    maxFileSizeBytes: 10 * 1024 * 1024, // 10MB
    timeoutMs: 30000,
    maxRetries: 0, // Mock doesn't need retries
  };
}
