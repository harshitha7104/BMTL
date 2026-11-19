// ============================================================
// API Client for FastAPI Backend
// Typed HTTP client for communicating with the ScrapTrust API
// ============================================================

import {
  Assessment,
  FeedbackSubmission,
  FeedbackRecord,
  ApiResponse,
  HealthResponse,
} from '../types/assessment';

import { API_BASE_URL } from './apiBase';

// Request timeout in milliseconds
const REQUEST_TIMEOUT_MS = 30000;

/**
 * Custom error class for API errors
 */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: Record<string, unknown>
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/**
 * Generic fetch wrapper with timeout and error handling
 */
async function fetchWithTimeout<T>(
  url: string,
  options: RequestInit = {}
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      // Try to parse error response
      let errorData: any;
      try {
        errorData = await response.json();
      } catch {
        errorData = { message: response.statusText };
      }

      throw new ApiError(
        response.status,
        errorData.error || 'UNKNOWN_ERROR',
        errorData.message || `HTTP ${response.status}`,
        errorData.details
      );
    }

    return await response.json();
  } catch (error) {
    clearTimeout(timeoutId);

    if (error instanceof ApiError) {
      throw error;
    }

    if (error instanceof Error) {
      if (error.name === 'AbortError') {
        throw new ApiError(408, 'TIMEOUT', 'Request timed out');
      }
      if (error.message.includes('Failed to fetch')) {
        throw new ApiError(0, 'NETWORK_ERROR', 'Backend unavailable. Please check your connection.');
      }
    }

    throw new ApiError(0, 'UNKNOWN_ERROR', 'An unexpected error occurred');
  }
}

/**
 * Health check endpoint
 */
export async function healthCheck(): Promise<HealthResponse> {
  return fetchWithTimeout<HealthResponse>(`${API_BASE_URL}/health`);
}

/**
 * Create a new assessment from uploaded images
 */
export async function createAssessment(files: File[]): Promise<ApiResponse<Assessment>> {
  const formData = new FormData();
  
  // Append each file to FormData
  // Note: Do NOT manually set Content-Type header — browser sets it with boundary
  files.forEach((file) => {
    formData.append('images', file);
  });

  return fetchWithTimeout<ApiResponse<Assessment>>(
    `${API_BASE_URL}/api/v1/assessments`,
    {
      method: 'POST',
      body: formData,
    }
  );
}

/**
 * Get an assessment by ID
 */
export async function getAssessment(assessmentId: string): Promise<ApiResponse<Assessment>> {
  return fetchWithTimeout<ApiResponse<Assessment>>(
    `${API_BASE_URL}/api/v1/assessments/${assessmentId}`
  );
}

/**
 * List all assessments
 */
export async function listAssessments(
  skip: number = 0,
  limit: number = 20
): Promise<ApiResponse<Assessment[]>> {
  return fetchWithTimeout<ApiResponse<Assessment[]>>(
    `${API_BASE_URL}/api/v1/assessments?skip=${skip}&limit=${limit}`
  );
}

/**
 * Submit feedback for an assessment
 */
export async function submitFeedback(
  assessmentId: string,
  feedback: Omit<FeedbackSubmission, 'assessment_id' | 'submitted_at'>
): Promise<ApiResponse<FeedbackRecord>> {
  return fetchWithTimeout<ApiResponse<FeedbackRecord>>(
    `${API_BASE_URL}/api/v1/assessments/${assessmentId}/feedback`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(feedback),
    }
  );
}

/**
 * Get all feedback for an assessment
 */
export async function getFeedback(
  assessmentId: string
): Promise<ApiResponse<FeedbackRecord[]>> {
  return fetchWithTimeout<ApiResponse<FeedbackRecord[]>>(
    `${API_BASE_URL}/api/v1/assessments/${assessmentId}/feedback`
  );
}

/**
 * Check if backend is available
 */
export async function isBackendAvailable(): Promise<boolean> {
  try {
    await healthCheck();
    return true;
  } catch {
    return false;
  }
}
