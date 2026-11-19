import React, { useState, useCallback, useRef } from 'react';
import {
  Upload as UploadIcon,
  X,
  AlertCircle,
  CheckCircle,
  Loader,
  Image,
  FileWarning,
} from 'lucide-react';

import { UploadFile } from '../types/assessment';
import { validateFileType, validateFileSize, computeFileHash } from '../services/imageAnalysis';
import { createAssessment } from '../services/assessmentService';
import { Assessment } from '../types/assessment';

interface UploadPageProps {
  onAssessmentComplete: (assessment: Assessment) => void;
}

const MAX_FILES = 5;
const MAX_SIZE_MB = 10;

export default function UploadPage({ onAssessmentComplete }: UploadPageProps) {
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFiles = useCallback(async (newFiles: FileList | File[]) => {
    setError(null);
    const fileArray = Array.from(newFiles);

    // Check max files
    if (files.length + fileArray.length > MAX_FILES) {
      setError(`Maximum ${MAX_FILES} images allowed. You currently have ${files.length} file(s).`);
      return;
    }

    const uploadFiles: UploadFile[] = [];

    for (const file of fileArray) {
      const id = crypto.randomUUID();
      const preview = URL.createObjectURL(file);

      // Validate file type
      const typeValidation = validateFileType(file);
      if (!typeValidation.valid) {
        uploadFiles.push({
          id,
          file,
          preview,
          name: file.name,
          size: file.size,
          type: file.type,
          validation_status: 'invalid',
          validation_error: typeValidation.error,
        });
        continue;
      }

      // Validate file size
      const sizeValidation = validateFileSize(file, MAX_SIZE_MB);
      if (!sizeValidation.valid) {
        uploadFiles.push({
          id,
          file,
          preview,
          name: file.name,
          size: file.size,
          type: file.type,
          validation_status: 'invalid',
          validation_error: sizeValidation.error,
        });
        continue;
      }

      // Compute hash for deduplication
      let hash: string | undefined;
      try {
        hash = await computeFileHash(file);
      } catch {
        // Hash computation is optional
      }

      uploadFiles.push({
        id,
        file,
        preview,
        name: file.name,
        size: file.size,
        type: file.type,
        hash,
        validation_status: 'valid',
      });
    }

    setFiles(prev => [...prev, ...uploadFiles]);
  }, [files.length]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files);
    }
  }, [handleFiles]);

  const removeFile = (id: string) => {
    setFiles(prev => {
      const file = prev.find(f => f.id === id);
      if (file) URL.revokeObjectURL(file.preview);
      return prev.filter(f => f.id !== id);
    });
  };

  const handleSubmit = async () => {
    const validFiles = files.filter(f => f.validation_status === 'valid');
    if (validFiles.length === 0) {
      setError('Please upload at least one valid image file.');
      return;
    }

    setIsProcessing(true);
    setError(null);

    try {
      const response = await createAssessment(validFiles);
      if (response.success && response.data) {
        onAssessmentComplete(response.data);
      } else {
        setError(response.error || 'Assessment processing failed. Please try again.');
      }
    } catch (err) {
      setError('An unexpected error occurred. Please try again.');
    } finally {
      setIsProcessing(false);
    }
  };

  const validFilesCount = files.filter(f => f.validation_status === 'valid').length;
  const invalidFilesCount = files.filter(f => f.validation_status === 'invalid').length;

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Page Header */}
      <div>
        <h2 className="text-2xl font-bold text-gray-900">New Assessment</h2>
        <p className="text-sm text-gray-500 mt-1">
          Upload photographs of scrap material for AI-assisted visual assessment
        </p>
      </div>

      {/* Guidelines */}
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4">
        <h3 className="text-sm font-semibold text-blue-900 mb-2">📸 Photography Guidelines</h3>
        <ul className="text-xs text-blue-800 space-y-1">
          <li>• Use even, diffused lighting — avoid harsh shadows or direct flash</li>
          <li>• Include a scale reference (coin, ruler) for size estimation</li>
          <li>• Capture multiple angles for complex geometries</li>
          <li>• Ensure the material fills at least 50% of the frame</li>
          <li>• Maximum {MAX_FILES} images, {MAX_SIZE_MB}MB each (JPEG, PNG, WebP)</li>
        </ul>
      </div>

      {/* Upload Area */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`relative border-2 border-dashed rounded-xl p-8 text-center transition-colors ${
          isDragging
            ? 'border-emerald-400 bg-emerald-50'
            : 'border-gray-300 hover:border-emerald-300 hover:bg-emerald-50/30'
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="image/jpeg,image/png,image/webp"
          className="hidden"
          onChange={(e) => e.target.files && handleFiles(e.target.files)}
        />

        <div className="flex flex-col items-center gap-3">
          <div className={`w-14 h-14 rounded-full flex items-center justify-center ${
            isDragging ? 'bg-emerald-100' : 'bg-gray-100'
          }`}>
            <UploadIcon className={`w-7 h-7 ${isDragging ? 'text-emerald-600' : 'text-gray-400'}`} />
          </div>
          <div>
            <p className="text-sm font-medium text-gray-900">
              Drag and drop images here, or{' '}
              <button
                onClick={() => fileInputRef.current?.click()}
                className="text-emerald-600 hover:text-emerald-700 font-semibold underline"
                disabled={isProcessing}
              >
                browse files
              </button>
            </p>
            <p className="text-xs text-gray-500 mt-1">
              {MAX_FILES} images max • JPEG, PNG, WebP • {MAX_SIZE_MB}MB each
            </p>
          </div>
        </div>
      </div>

      {/* Error Message */}
      {error && (
        <div className="flex items-start gap-3 p-4 bg-red-50 border border-red-200 rounded-xl">
          <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-red-800">{error}</p>
          </div>
        </div>
      )}

      {/* File Previews */}
      {files.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900">
              Uploaded Files ({validFilesCount} valid{invalidFilesCount > 0 ? `, ${invalidFilesCount} invalid` : ''})
            </h3>
            <button
              onClick={() => {
                files.forEach(f => URL.revokeObjectURL(f.preview));
                setFiles([]);
              }}
              className="text-xs text-gray-500 hover:text-red-600 transition-colors"
              disabled={isProcessing}
            >
              Clear all
            </button>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {files.map(file => (
              <div
                key={file.id}
                className={`relative group rounded-lg overflow-hidden border-2 ${
                  file.validation_status === 'invalid'
                    ? 'border-red-300'
                    : file.validation_status === 'valid'
                    ? 'border-emerald-200'
                    : 'border-gray-200'
                }`}
              >
                <div className="aspect-square bg-gray-100">
                  {file.validation_status !== 'invalid' ? (
                    <img
                      src={file.preview}
                      alt={file.name}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="w-full h-full flex flex-col items-center justify-center text-gray-400">
                      <FileWarning className="w-8 h-8 mb-1" />
                      <span className="text-xs">Invalid file</span>
                    </div>
                  )}
                </div>

                {/* Status Badge */}
                <div className="absolute top-2 left-2">
                  {file.validation_status === 'valid' && (
                    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-emerald-500 text-white rounded text-xs">
                      <CheckCircle className="w-3 h-3" />
                    </span>
                  )}
                  {file.validation_status === 'invalid' && (
                    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-red-500 text-white rounded text-xs">
                      <X className="w-3 h-3" />
                    </span>
                  )}
                  {file.validation_status === 'processing' && (
                    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-blue-500 text-white rounded text-xs">
                      <Loader className="w-3 h-3 animate-spin" />
                    </span>
                  )}
                </div>

                {/* Remove Button */}
                {!isProcessing && (
                  <button
                    onClick={() => removeFile(file.id)}
                    className="absolute top-2 right-2 w-6 h-6 bg-black/60 hover:bg-black/80 text-white rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}

                {/* File Info */}
                <div className="p-2 bg-white">
                  <p className="text-xs font-medium text-gray-700 truncate">{file.name}</p>
                  <p className="text-xs text-gray-400">
                    {(file.size / 1024).toFixed(0)} KB
                    {file.validation_error && (
                      <span className="text-red-500 ml-1">• {file.validation_error}</span>
                    )}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Processing State */}
      {isProcessing && (
        <div className="bg-white border border-gray-200 rounded-xl p-6">
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 border-3 border-emerald-200 border-t-emerald-600 rounded-full animate-spin"></div>
            <div>
              <p className="text-sm font-medium text-gray-900">Processing Assessment</p>
              <p className="text-xs text-gray-500 mt-0.5">
                Analyzing image quality and running AI assessment... This may take a moment.
              </p>
            </div>
          </div>
          <div className="mt-4 space-y-2">
            <ProcessingStep label="Validating uploaded images" done={true} />
            <ProcessingStep label="Assessing image quality" done={true} />
            <ProcessingStep label="Running AI visual analysis" done={false} active={true} />
            <ProcessingStep label="Generating structured assessment" done={false} />
          </div>
        </div>
      )}

      {/* Submit Button */}
      {files.length > 0 && !isProcessing && (
        <div className="flex justify-end gap-3">
          <button
            onClick={() => {
              files.forEach(f => URL.revokeObjectURL(f.preview));
              setFiles([]);
              setError(null);
            }}
            className="px-4 py-2.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
          >
            Clear
          </button>
          <button
            onClick={handleSubmit}
            disabled={validFilesCount === 0}
            className="inline-flex items-center gap-2 px-6 py-2.5 bg-emerald-600 text-white rounded-lg text-sm font-medium hover:bg-emerald-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
          >
            <Image className="w-4 h-4" />
            Start Assessment ({validFilesCount} image{validFilesCount !== 1 ? 's' : ''})
          </button>
        </div>
      )}
    </div>
  );
}

function ProcessingStep({ label, done, active }: { label: string; done: boolean; active?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      {done ? (
        <CheckCircle className="w-4 h-4 text-emerald-500" />
      ) : active ? (
        <Loader className="w-4 h-4 text-blue-500 animate-spin" />
      ) : (
        <div className="w-4 h-4 rounded-full border-2 border-gray-200"></div>
      )}
      <span className={`text-sm ${done ? 'text-gray-600' : active ? 'text-gray-900 font-medium' : 'text-gray-400'}`}>
        {label}
      </span>
    </div>
  );
}
