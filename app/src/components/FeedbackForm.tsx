import React, { useState } from 'react';
import {
  MessageSquare,
  Send,
  AlertCircle,
  CheckCircle,
  Loader,
} from 'lucide-react';
import {
  Assessment,
  FeedbackCategory,
  MaterialFamily,
  ScrapForm,
  SurfaceCondition,
  VisibleContamination,
} from '../types/assessment';
import { submitFeedback } from '../services/assessmentService';

interface FeedbackFormProps {
  assessment: Assessment;
  onClose: () => void;
  onSubmitted?: () => void;
}

export default function FeedbackForm({ assessment, onClose, onSubmitted }: FeedbackFormProps) {
  const [category, setCategory] = useState<FeedbackCategory>('correction');
  const [reviewerName, setReviewerName] = useState('');
  const [notes, setNotes] = useState('');
  
  // Correction fields
  const [materialFamily, setMaterialFamily] = useState<MaterialFamily | ''>('');
  const [scrapForm, setScrapForm] = useState<ScrapForm | ''>('');
  const [surfaceCondition, setSurfaceCondition] = useState<SurfaceCondition | ''>('');
  const [contamination, setContamination] = useState<VisibleContamination | ''>('');
  
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!reviewerName.trim()) {
      setError('Please enter your name');
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const feedback = {
        reviewer_name: reviewerName.trim(),
        feedback_category: category,
        corrections: {
          material_family: materialFamily || undefined,
          scrap_form: scrapForm || undefined,
          surface_condition: surfaceCondition || undefined,
          contamination: contamination || undefined,
          additional_notes: notes.trim() || undefined,
        },
        verified: false,
      };

      const response = await submitFeedback(assessment.assessment_id, feedback);
      
      if (response.success) {
        setSuccess(true);
        setTimeout(() => {
          onSubmitted?.();
          onClose();
        }, 2000);
      } else {
        setError(response.error || 'Failed to submit feedback');
      }
    } catch (err) {
      setError('An unexpected error occurred. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  if (success) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <div className="flex items-center gap-3 text-emerald-600">
          <CheckCircle className="w-6 h-6" />
          <div>
            <p className="font-semibold">Feedback Submitted</p>
            <p className="text-sm text-gray-600 mt-1">
              Thank you for your feedback. It has been recorded separately from the original assessment.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <MessageSquare className="w-5 h-5 text-gray-600" />
          <h3 className="text-lg font-semibold text-gray-900">Submit Feedback</h3>
        </div>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-gray-600 transition-colors"
        >
          ✕
        </button>
      </div>

      <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
        <p className="text-xs text-blue-800">
          <strong>Important:</strong> Feedback is stored separately from the original AI assessment.
          It does not automatically modify the assessment or trigger model retraining.
          All feedback requires human verification before being used.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Reviewer Name */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Your Name *
          </label>
          <input
            type="text"
            value={reviewerName}
            onChange={(e) => setReviewerName(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            placeholder="Enter your name"
            required
          />
        </div>

        {/* Feedback Category */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Feedback Category
          </label>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value as FeedbackCategory)}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          >
            <option value="correction">Correction — Factual correction to AI output</option>
            <option value="clarification">Clarification — Additional context or explanation</option>
            <option value="disagreement">Disagreement — Disagree with AI assessment</option>
            <option value="confirmation">Confirmation — Confirm AI assessment is correct</option>
            <option value="additional_info">Additional Info — Provide new information</option>
            <option value="other">Other</option>
          </select>
        </div>

        {/* Correction Fields */}
        {(category === 'correction' || category === 'disagreement') && (
          <div className="space-y-3 p-3 bg-gray-50 rounded-lg">
            <p className="text-xs font-medium text-gray-700">Corrections (optional)</p>
            
            <div>
              <label className="block text-xs text-gray-600 mb-1">Material Family</label>
              <select
                value={materialFamily}
                onChange={(e) => setMaterialFamily(e.target.value as MaterialFamily)}
                className="w-full px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-emerald-500"
              >
                <option value="">— No change —</option>
                <option value="ferrous">Ferrous</option>
                <option value="non_ferrous">Non-Ferrous</option>
                <option value="mixed">Mixed</option>
                <option value="electronic">Electronic</option>
                <option value="plastic">Plastic</option>
                <option value="organic">Organic</option>
                <option value="hazardous">Hazardous</option>
                <option value="unidentifiable">Unidentifiable</option>
              </select>
            </div>

            <div>
              <label className="block text-xs text-gray-600 mb-1">Scrap Form</label>
              <select
                value={scrapForm}
                onChange={(e) => setScrapForm(e.target.value as ScrapForm)}
                className="w-full px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-emerald-500"
              >
                <option value="">— No change —</option>
                <option value="sheet">Sheet</option>
                <option value="bar">Bar</option>
                <option value="pipe">Pipe</option>
                <option value="wire">Wire</option>
                <option value="turning">Turning</option>
                <option value="casting">Casting</option>
                <option value="forging">Forging</option>
                <option value="machined_part">Machined Part</option>
                <option value="electronic_component">Electronic Component</option>
                <option value="fragment">Fragment</option>
                <option value="irregular">Irregular</option>
                <option value="unidentifiable">Unidentifiable</option>
              </select>
            </div>

            <div>
              <label className="block text-xs text-gray-600 mb-1">Surface Condition</label>
              <select
                value={surfaceCondition}
                onChange={(e) => setSurfaceCondition(e.target.value as SurfaceCondition)}
                className="w-full px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-emerald-500"
              >
                <option value="">— No change —</option>
                <option value="clean">Clean</option>
                <option value="lightly_rusted">Lightly Rusted</option>
                <option value="heavily_rusted">Heavily Rusted</option>
                <option value="painted">Painted</option>
                <option value="coated">Coated</option>
                <option value="oxidized">Oxidized</option>
                <option value="contaminated">Contaminated</option>
                <option value="corroded">Corroded</option>
                <option value="unidentifiable">Unidentifiable</option>
              </select>
            </div>

            <div>
              <label className="block text-xs text-gray-600 mb-1">Visible Contamination</label>
              <select
                value={contamination}
                onChange={(e) => setContamination(e.target.value as VisibleContamination)}
                className="w-full px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-emerald-500"
              >
                <option value="">— No change —</option>
                <option value="none_visible">None Visible</option>
                <option value="oil_grease">Oil/Grease</option>
                <option value="dirt_soil">Dirt/Soil</option>
                <option value="paint">Paint</option>
                <option value="rubber">Rubber</option>
                <option value="plastic">Plastic</option>
                <option value="concrete">Concrete</option>
                <option value="organic">Organic</option>
                <option value="chemical_residue">Chemical Residue</option>
                <option value="unknown">Unknown</option>
              </select>
            </div>
          </div>
        )}

        {/* Additional Notes */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Additional Notes
          </label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            placeholder="Provide any additional context, explanations, or comments..."
          />
        </div>

        {/* Error Message */}
        {error && (
          <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-lg">
            <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
            <p className="text-sm text-red-800">{error}</p>
          </div>
        )}

        {/* Submit Button */}
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
            disabled={isSubmitting}
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={isSubmitting}
            className="inline-flex items-center gap-2 px-4 py-2 bg-emerald-600 text-white rounded-lg text-sm font-medium hover:bg-emerald-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSubmitting ? (
              <>
                <Loader className="w-4 h-4 animate-spin" />
                Submitting...
              </>
            ) : (
              <>
                <Send className="w-4 h-4" />
                Submit Feedback
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
