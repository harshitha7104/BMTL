// ============================================================
// Assessment Service — Unified Interface
// Switches between mock service and real API based on configuration
// ============================================================

import {
  Assessment,
  FeedbackSubmission,
  FeedbackRecord,
  ApiResponse,
  UploadFile,
} from '../types/assessment';
import * as apiClient from './apiClient';
import * as mockService from './mockAssessmentService';

// Service mode: 'mock' for development, 'api' for backend integration
// Can be set via VITE_SERVICE_MODE environment variable
const SERVICE_MODE = (import.meta.env.VITE_SERVICE_MODE || 'mock') as 'mock' | 'api';

/**
 * Create a new assessment from uploaded images
 */
export async function createAssessment(files: UploadFile[]): Promise<ApiResponse<Assessment>> {
  if (SERVICE_MODE === 'api') {
    // Extract File objects from UploadFile array
    const fileObjects = files
      .filter(f => f.file && f.validation_status === 'valid')
      .map(f => f.file!);
    
    return apiClient.createAssessment(fileObjects);
  } else {
    return mockService.createAssessment(files);
  }
}

/**
 * Get an assessment by ID
 */
export async function getAssessment(assessmentId: string): Promise<ApiResponse<Assessment>> {
  if (SERVICE_MODE === 'api') {
    return apiClient.getAssessment(assessmentId);
  } else {
    return mockService.getAssessment(assessmentId);
  }
}

/**
 * List all assessments
 */
export async function listAssessments(
  skip: number = 0,
  limit: number = 20
): Promise<ApiResponse<Assessment[]>> {
  if (SERVICE_MODE === 'api') {
    return apiClient.listAssessments(skip, limit);
  } else {
    return mockService.getAllAssessments();
  }
}

/**
 * Submit feedback for an assessment
 */
export async function submitFeedback(
  assessmentId: string,
  feedback: Omit<FeedbackSubmission, 'assessment_id' | 'submitted_at'>
): Promise<ApiResponse<FeedbackRecord>> {
  if (SERVICE_MODE === 'api') {
    return apiClient.submitFeedback(assessmentId, feedback);
  } else {
    return mockService.submitFeedback({
      assessment_id: assessmentId,
      ...feedback,
      submitted_at: new Date().toISOString(),
    });
  }
}

/**
 * Get all feedback for an assessment
 */
export async function getFeedback(
  assessmentId: string
): Promise<ApiResponse<FeedbackRecord[]>> {
  if (SERVICE_MODE === 'api') {
    return apiClient.getFeedback(assessmentId);
  } else {
    // Mock service doesn't implement this yet — return empty
    return { success: true, data: [] };
  }
}

/**
 * Check if backend is available (API mode only)
 */
export async function isBackendAvailable(): Promise<boolean> {
  if (SERVICE_MODE === 'api') {
    return apiClient.isBackendAvailable();
  } else {
    return true; // Mock is always available
  }
}

/**
 * Get current service mode
 */
export function getServiceMode(): 'mock' | 'api' {
  return SERVICE_MODE;
}

/**
 * Get dashboard statistics
 */
export async function getDashboardStats(): Promise<ApiResponse<any>> {
  if (SERVICE_MODE === 'api') {
    // API doesn't have a dedicated stats endpoint yet
    // Calculate from list of assessments
    const response = await apiClient.listAssessments(0, 1000);
    if (!response.success || !response.data) {
      return { success: false, error: 'Failed to load stats' };
    }
    
    const assessments = response.data;
    const stats = {
      total_assessments: assessments.length,
      completed: assessments.filter(a => a.status === 'completed').length,
      pending_review: assessments.filter(a => a.status === 'requires_review').length,
      failed: assessments.filter(a => a.status === 'failed').length,
      avg_confidence: assessments.length > 0
        ? assessments.reduce((sum, a) => sum + a.confidence, 0) / assessments.length
        : 0,
    };
    
    return { success: true, data: stats };
  } else {
    return mockService.getDashboardStats();
  }
}
