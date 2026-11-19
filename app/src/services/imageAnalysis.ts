// ============================================================
// Image Quality Analysis Service (Client-Side)
// Performs basic image quality checks before sending to backend
// ============================================================

import { EvidenceQuality, QualityIssue } from '../types/assessment';

export interface ImageAnalysisResult {
  width: number;
  height: number;
  fileSize: number;
  brightness: number;
  contrast: number;
  sharpness: number;
}

/**
 * Analyzes image quality using canvas-based heuristics.
 * This is a client-side pre-check; the backend performs deeper analysis.
 */
export async function analyzeImageQuality(file: File): Promise<{
  analysis: ImageAnalysisResult;
  quality: EvidenceQuality;
}> {
  const analysis = await performImageAnalysis(file);
  const quality = evaluateQuality(analysis);
  return { analysis, quality };
}

async function performImageAnalysis(file: File): Promise<ImageAnalysisResult> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);

    img.onload = () => {
      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        reject(new Error('Canvas context not available'));
        return;
      }

      // Sample a smaller version for analysis
      const maxSize = 200;
      const scale = Math.min(maxSize / img.width, maxSize / img.height, 1);
      canvas.width = img.width * scale;
      canvas.height = img.height * scale;

      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const data = imageData.data;

      // Calculate brightness
      let totalBrightness = 0;
      for (let i = 0; i < data.length; i += 4) {
        const r = data[i];
        const g = data[i + 1];
        const b = data[i + 2];
        totalBrightness += (r * 0.299 + g * 0.587 + b * 0.114) / 255;
      }
      const brightness = totalBrightness / (data.length / 4);

      // Calculate contrast (standard deviation of brightness)
      let varianceSum = 0;
      for (let i = 0; i < data.length; i += 4) {
        const r = data[i];
        const g = data[i + 1];
        const b = data[i + 2];
        const pixelBrightness = (r * 0.299 + g * 0.587 + b * 0.114) / 255;
        varianceSum += Math.pow(pixelBrightness - brightness, 2);
      }
      const contrast = Math.sqrt(varianceSum / (data.length / 4));

      // Calculate sharpness (Laplacian approximation)
      let sharpnessSum = 0;
      let sharpnessCount = 0;
      const w = canvas.width;
      for (let y = 1; y < canvas.height - 1; y++) {
        for (let x = 1; x < w - 1; x++) {
          const idx = (y * w + x) * 4;
          const center = data[idx] * 0.299 + data[idx + 1] * 0.587 + data[idx + 2] * 0.114;
          const top = data[((y - 1) * w + x) * 4] * 0.299 + data[((y - 1) * w + x) * 4 + 1] * 0.587 + data[((y - 1) * w + x) * 4 + 2] * 0.114;
          const bottom = data[((y + 1) * w + x) * 4] * 0.299 + data[((y + 1) * w + x) * 4 + 1] * 0.587 + data[((y + 1) * w + x) * 4 + 2] * 0.114;
          const left = data[(y * w + (x - 1)) * 4] * 0.299 + data[(y * w + (x - 1)) * 4 + 1] * 0.587 + data[(y * w + (x - 1)) * 4 + 2] * 0.114;
          const right = data[(y * w + (x + 1)) * 4] * 0.299 + data[(y * w + (x + 1)) * 4 + 1] * 0.587 + data[(y * w + (x + 1)) * 4 + 2] * 0.114;
          sharpnessSum += Math.abs(4 * center - top - bottom - left - right);
          sharpnessCount++;
        }
      }
      const sharpness = sharpnessCount > 0 ? sharpnessSum / sharpnessCount / 255 : 0;

      URL.revokeObjectURL(url);

      resolve({
        width: img.width,
        height: img.height,
        fileSize: file.size,
        brightness,
        contrast,
        sharpness,
      });
    };

    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('Failed to load image'));
    };

    img.src = url;
  });
}

function evaluateQuality(analysis: ImageAnalysisResult): EvidenceQuality {
  const issues: QualityIssue[] = [];
  let score = 100;

  // Check resolution
  const totalPixels = analysis.width * analysis.height;
  if (totalPixels < 100000) {
    issues.push({
      issue: 'low_resolution',
      severity: 'high',
      description: `Image resolution (${analysis.width}x${analysis.height}) is too low for reliable analysis. Minimum 500x200 pixels recommended.`,
    });
    score -= 30;
  } else if (totalPixels < 500000) {
    issues.push({
      issue: 'moderate_resolution',
      severity: 'medium',
      description: `Image resolution (${analysis.width}x${analysis.height}) is acceptable but higher resolution would improve analysis accuracy.`,
    });
    score -= 10;
  }

  // Check brightness
  if (analysis.brightness < 0.15) {
    issues.push({
      issue: 'too_dark',
      severity: 'high',
      description: 'Image is excessively dark. Surface details and material characteristics may not be visible.',
    });
    score -= 25;
  } else if (analysis.brightness < 0.25) {
    issues.push({
      issue: 'dark',
      severity: 'medium',
      description: 'Image is somewhat dark. Some surface details may be difficult to discern.',
    });
    score -= 10;
  } else if (analysis.brightness > 0.9) {
    issues.push({
      issue: 'overexposed',
      severity: 'high',
      description: 'Image is overexposed. Surface details may be washed out and lost.',
    });
    score -= 25;
  } else if (analysis.brightness > 0.8) {
    issues.push({
      issue: 'bright',
      severity: 'medium',
      description: 'Image is quite bright. Some detail may be lost in highlights.',
    });
    score -= 10;
  }

  // Check contrast
  if (analysis.contrast < 0.05) {
    issues.push({
      issue: 'low_contrast',
      severity: 'medium',
      description: 'Image has very low contrast. Material boundaries and surface features may be difficult to distinguish.',
    });
    score -= 15;
  }

  // Check sharpness (blur detection)
  if (analysis.sharpness < 0.02) {
    issues.push({
      issue: 'excessive_blur',
      severity: 'high',
      description: 'Image appears significantly blurred. Fine details needed for material identification are likely lost.',
    });
    score -= 30;
  } else if (analysis.sharpness < 0.05) {
    issues.push({
      issue: 'moderate_blur',
      severity: 'medium',
      description: 'Image shows moderate blur. Some fine details may be affected.',
    });
    score -= 15;
  }

  // Determine overall status
  score = Math.max(0, score);
  let status: EvidenceQuality['status'];
  if (score >= 70) {
    status = 'sufficient';
  } else if (score >= 40) {
    status = 'partially_sufficient';
  } else {
    status = 'insufficient';
  }

  // Generate recommendations
  const recommended: string[] = [];
  if (issues.some(i => i.issue.includes('dark') || i.issue === 'overexposed')) {
    recommended.push('Take photos in even, diffused lighting without harsh shadows or direct flash');
  }
  if (issues.some(i => i.issue.includes('blur'))) {
    recommended.push('Ensure camera is steady and focus is locked on the material surface');
  }
  if (issues.some(i => i.issue.includes('resolution'))) {
    recommended.push('Use a higher resolution camera or move closer to capture more detail');
  }
  if (issues.some(i => i.issue === 'low_contrast')) {
    recommended.push('Ensure adequate lighting contrast to distinguish material features');
  }
  recommended.push('Include a reference object (coin or ruler) for scale');
  recommended.push('Capture multiple angles if the material has complex geometry');

  return {
    status,
    issues,
    recommended_additional_photos: recommended,
    human_review_required: status === 'insufficient',
    overall_score: score,
  };
}

/**
 * Validates file type by checking magic bytes (not just extension)
 */
export function validateFileType(file: File): { valid: boolean; error?: string } {
  const allowedTypes = ['image/jpeg', 'image/png', 'image/webp', 'image/heic'];
  const allowedExtensions = ['.jpg', '.jpeg', '.png', '.webp', '.heic'];

  // Check MIME type
  if (!allowedTypes.includes(file.type) && file.type !== '') {
    return { valid: false, error: `File type "${file.type}" is not supported. Accepted formats: JPEG, PNG, WebP.` };
  }

  // Check extension as secondary validation
  const ext = '.' + file.name.split('.').pop()?.toLowerCase();
  if (!allowedExtensions.includes(ext)) {
    return { valid: false, error: `File extension "${ext}" is not supported. Accepted formats: .jpg, .jpeg, .png, .webp` };
  }

  return { valid: true };
}

/**
 * Validates file size
 */
export function validateFileSize(file: File, maxSizeMB: number = 10): { valid: boolean; error?: string } {
  const maxSizeBytes = maxSizeMB * 1024 * 1024;
  if (file.size > maxSizeBytes) {
    return {
      valid: false,
      error: `File size (${(file.size / 1024 / 1024).toFixed(1)}MB) exceeds maximum allowed size of ${maxSizeMB}MB.`,
    };
  }
  if (file.size === 0) {
    return { valid: false, error: 'File is empty (0 bytes).' };
  }
  return { valid: true };
}

/**
 * Computes a simple hash of the file for deduplication
 */
export async function computeFileHash(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}
