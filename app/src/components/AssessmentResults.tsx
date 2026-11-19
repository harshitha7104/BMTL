import React, { useState } from 'react';
import {
  Eye,
  Brain,
  HelpCircle,
  AlertTriangle,
  CheckCircle,
  Shield,
  Camera,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  FileText,
  Download,
  Clock,
  Cpu,
  MessageSquare,
} from 'lucide-react';
import { Assessment } from '../types/assessment';
import TrustReport from './TrustReport';
import FeedbackForm from './FeedbackForm';
import {
  formatEnum,
  formatConfidence,
  getConfidenceColor,
  getConfidenceBarColor,
  formatReviewTrigger,
} from '../utils/formatters';

interface AssessmentResultsProps {
  assessment: Assessment;
  onBack: () => void;
  onNewAssessment: () => void;
}

export default function AssessmentResults({ assessment, onBack, onNewAssessment }: AssessmentResultsProps) {
  const [showTrustReport, setShowTrustReport] = useState(false);
  const [showFeedbackForm, setShowFeedbackForm] = useState(false);
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    observations: true,
    inferences: true,
    unknowns: true,
    quality: true,
  });

  const toggleSection = (section: string) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };

  if (showTrustReport) {
    return <TrustReport assessment={assessment} onBack={() => setShowTrustReport(false)} />;
  }

  if (showFeedbackForm) {
    return (
      <div className="max-w-2xl mx-auto">
        <FeedbackForm
          assessment={assessment}
          onClose={() => setShowFeedbackForm(false)}
          onSubmitted={() => {
            // Could refresh assessment or show success message
          }}
        />
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <div className="flex items-center gap-2 text-sm text-gray-500 mb-1">
            <button onClick={onBack} className="hover:text-emerald-600 transition-colors">Dashboard</button>
            <span>/</span>
            <span className="text-gray-900 font-medium">{assessment.assessment_id}</span>
          </div>
          <h2 className="text-2xl font-bold text-gray-900">Assessment Results</h2>
          <p className="text-sm text-gray-500 mt-1">
            Generated {new Date(assessment.created_at).toLocaleString()}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowFeedbackForm(true)}
            className="inline-flex items-center gap-2 px-4 py-2 bg-white border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
          >
            <MessageSquare className="w-4 h-4" />
            Submit Feedback
          </button>
          <button
            onClick={() => setShowTrustReport(true)}
            className="inline-flex items-center gap-2 px-4 py-2 bg-white border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
          >
            <Shield className="w-4 h-4" />
            Trust Report
          </button>
          <button
            onClick={onNewAssessment}
            className="inline-flex items-center gap-2 px-4 py-2 bg-emerald-600 text-white rounded-lg text-sm font-medium hover:bg-emerald-700 transition-colors"
          >
            New Assessment
          </button>
        </div>
      </div>

      {/* Status Banner */}
      {assessment.human_review_required && (
        <div className="flex items-start gap-3 p-4 bg-amber-50 border border-amber-200 rounded-xl">
          <AlertTriangle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="text-sm font-semibold text-amber-900">Human Review Required</p>
            <p className="text-xs text-amber-800 mt-0.5">
              This assessment has been flagged for human expert review.
              Do not rely solely on these findings for commercial decisions.
            </p>
            {assessment.human_review_reasons && assessment.human_review_reasons.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {assessment.human_review_reasons.map((reason, idx) => (
                  <span
                    key={idx}
                    className="inline-flex items-center px-2 py-0.5 bg-amber-100 text-amber-800 rounded text-xs font-medium"
                  >
                    {formatReviewTrigger(reason)}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Confidence Overview */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-900">Overall Confidence</h3>
          <span className={`text-2xl font-bold ${getConfidenceColor(assessment.confidence)}`}>
            {Math.round(assessment.confidence * 100)}%
          </span>
        </div>
        <div className="w-full bg-gray-100 rounded-full h-2.5">
          <div
            className={`h-2.5 rounded-full transition-all ${getConfidenceBarColor(assessment.confidence)}`}
            style={{ width: `${assessment.confidence * 100}%` }}
          ></div>
        </div>
        <p className="text-xs text-gray-500 mt-2">
          {assessment.confidence >= 0.7
            ? 'Moderate confidence — findings are visually supported but require verification for commercial decisions.'
            : assessment.confidence >= 0.4
            ? 'Low-moderate confidence — significant uncertainty remains. Physical testing strongly recommended.'
            : 'Low confidence — visual evidence is insufficient. Multiple additional photographs and physical tests required.'}
        </p>
      </div>

      {/* Evidence Quality */}
      <CollapsibleSection
        title="Evidence Quality"
        icon={Camera}
        expanded={expandedSections.quality}
        onToggle={() => toggleSection('quality')}
        badge={
          <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
            assessment.evidence_quality.status === 'sufficient'
              ? 'bg-emerald-50 text-emerald-700'
              : assessment.evidence_quality.status === 'partially_sufficient'
              ? 'bg-amber-50 text-amber-700'
              : 'bg-red-50 text-red-700'
          }`}>
            {assessment.evidence_quality.status.replace('_', ' ')}
          </span>
        }
      >
        <div className="space-y-4">
          {/* Quality Score */}
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <div className="flex justify-between text-xs text-gray-500 mb-1">
                <span>Quality Score</span>
                <span>{assessment.evidence_quality.overall_score}/100</span>
              </div>
              <div className="w-full bg-gray-100 rounded-full h-2">
                <div
                  className={`h-2 rounded-full ${
                    assessment.evidence_quality.overall_score >= 70
                      ? 'bg-emerald-500'
                      : assessment.evidence_quality.overall_score >= 40
                      ? 'bg-amber-500'
                      : 'bg-red-500'
                  }`}
                  style={{ width: `${assessment.evidence_quality.overall_score}%` }}
                ></div>
              </div>
            </div>
          </div>

          {/* Issues */}
          {assessment.evidence_quality.issues.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-700 mb-2">Detected Issues:</p>
              <div className="space-y-2">
                {assessment.evidence_quality.issues.map((issue, idx) => (
                  <div key={idx} className="flex items-start gap-2 p-2 bg-gray-50 rounded-lg">
                    <span className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${
                      issue.severity === 'critical' || issue.severity === 'high'
                        ? 'bg-red-500'
                        : issue.severity === 'medium'
                        ? 'bg-amber-500'
                        : 'bg-blue-500'
                    }`}></span>
                    <div>
                      <p className="text-xs font-medium text-gray-800">{issue.issue.replace(/_/g, ' ')}</p>
                      <p className="text-xs text-gray-500">{issue.description}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Recommendations */}
          {assessment.evidence_quality.recommended_additional_photos.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-700 mb-2">Recommended Additional Photos:</p>
              <ul className="space-y-1">
                {assessment.evidence_quality.recommended_additional_photos.map((rec, idx) => (
                  <li key={idx} className="text-xs text-gray-600 flex items-start gap-2">
                    <Camera className="w-3 h-3 text-gray-400 mt-0.5 flex-shrink-0" />
                    {rec}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </CollapsibleSection>

      {/* Visual Observations (OBSERVED) */}
      <CollapsibleSection
        title="Visual Observations"
        subtitle="Directly visible characteristics in the uploaded images"
        icon={Eye}
        expanded={expandedSections.observations}
        onToggle={() => toggleSection('observations')}
        color="blue"
        count={assessment.observed.length}
      >
        <div className="space-y-3">
          {assessment.observed.map((obs, idx) => (
            <div key={idx} className="p-3 bg-blue-50 border border-blue-100 rounded-lg">
              <p className="text-sm font-medium text-gray-900">{obs.finding}</p>
              <p className="text-xs text-gray-600 mt-1">
                <span className="font-medium">Evidence:</span> {obs.supporting_evidence}
              </p>
              <span className="inline-block mt-1.5 px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs">
                {obs.category}
              </span>
            </div>
          ))}
          {assessment.observed.length === 0 && (
            <p className="text-sm text-gray-500 italic">No direct observations could be made from the provided images.</p>
          )}
        </div>
      </CollapsibleSection>

      {/* Inferences (INFERRED) */}
      <CollapsibleSection
        title="Inferences"
        subtitle="Tentative interpretations based on visible evidence — each with confidence level and limitations"
        icon={Brain}
        expanded={expandedSections.inferences}
        onToggle={() => toggleSection('inferences')}
        color="amber"
        count={assessment.inferred.length}
      >
        <div className="space-y-3">
          {assessment.inferred.map((inf, idx) => (
            <div key={idx} className="p-3 bg-amber-50 border border-amber-100 rounded-lg">
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm font-medium text-gray-900">{inf.finding}</p>
                <span className={`flex-shrink-0 px-2 py-0.5 rounded-full text-xs font-bold ${
                  inf.confidence >= 0.7
                    ? 'bg-emerald-100 text-emerald-700'
                    : inf.confidence >= 0.4
                    ? 'bg-amber-100 text-amber-700'
                    : 'bg-red-100 text-red-700'
                }`}>
                  {Math.round(inf.confidence * 100)}%
                </span>
              </div>
              <div className="mt-2 space-y-1.5">
                <p className="text-xs text-gray-600">
                  <span className="font-medium text-gray-700">Visual Evidence:</span> {inf.supporting_visual_evidence}
                </p>
                <p className="text-xs text-gray-600">
                  <span className="font-medium text-gray-700">Limitations:</span> {inf.limitations}
                </p>
              </div>
              <span className="inline-block mt-2 px-2 py-0.5 bg-amber-100 text-amber-700 rounded text-xs">
                {inf.category.replace(/_/g, ' ')}
              </span>
            </div>
          ))}
          {assessment.inferred.length === 0 && (
            <p className="text-sm text-gray-500 italic">No inferences could be drawn from the available evidence.</p>
          )}
        </div>
      </CollapsibleSection>

      {/* Unknowns (UNKNOWN) */}
      <CollapsibleSection
        title="Unknown — Cannot Be Determined"
        subtitle="Information that cannot be established from the available visual evidence"
        icon={HelpCircle}
        expanded={expandedSections.unknowns}
        onToggle={() => toggleSection('unknowns')}
        color="red"
        count={assessment.unknown.length}
      >
        <div className="space-y-3">
          {assessment.unknown.map((unk, idx) => (
            <div key={idx} className="p-3 bg-red-50 border border-red-100 rounded-lg">
              <p className="text-sm font-medium text-gray-900">{unk.item}</p>
              <div className="mt-1.5 space-y-1">
                <p className="text-xs text-gray-600">
                  <span className="font-medium text-gray-700">Reason:</span> {unk.reason}
                </p>
                <p className="text-xs text-gray-600">
                  <span className="font-medium text-gray-700">Required Evidence:</span> {unk.required_evidence}
                </p>
              </div>
            </div>
          ))}
          {assessment.unknown.length === 0 && (
            <p className="text-sm text-gray-500 italic">No unknowns identified.</p>
          )}
        </div>
      </CollapsibleSection>

      {/* Proposed Assessment */}
      {assessment.proposed_assessment && (
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
            <FileText className="w-4 h-4 text-gray-500" />
            Proposed Assessment (Unverified)
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
            <InfoRow label="Material Family" value={formatEnum(assessment.proposed_assessment.material_family)} />
            <InfoRow label="Scrap Form" value={formatEnum(assessment.proposed_assessment.scrap_form)} />
            <InfoRow label="Surface Condition" value={formatEnum(assessment.proposed_assessment.surface_condition)} />
            <InfoRow label="Contamination" value={formatEnum(assessment.proposed_assessment.visible_contamination)} />
          </div>
          <p className="text-sm text-gray-700 mb-3">{assessment.proposed_assessment.description}</p>

          {assessment.proposed_assessment.estimated_grade_hint && (
            <div className="p-2 bg-gray-50 rounded-lg mb-3">
              <p className="text-xs text-gray-600">
                <span className="font-medium">Grade Hint:</span> {assessment.proposed_assessment.estimated_grade_hint}
                <span className="text-gray-400 ml-1">(confidence: {Math.round(assessment.proposed_assessment.grade_hint_confidence * 100)}%)</span>
              </p>
            </div>
          )}

          {assessment.proposed_assessment.caveats.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-700 mb-1.5">⚠️ Caveats:</p>
              <ul className="space-y-1">
                {assessment.proposed_assessment.caveats.map((caveat, idx) => (
                  <li key={idx} className="text-xs text-gray-600 flex items-start gap-1.5">
                    <span className="text-amber-500 mt-0.5">•</span>
                    {caveat}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Missing Evidence & Next Steps */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {assessment.missing_evidence.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Missing Evidence</h3>
            <ul className="space-y-2">
              {assessment.missing_evidence.map((item, idx) => (
                <li key={idx} className="text-xs text-gray-600 flex items-start gap-2">
                  <Camera className="w-3 h-3 text-gray-400 mt-0.5 flex-shrink-0" />
                  {item}
                </li>
              ))}
            </ul>
          </div>
        )}

        {assessment.recommended_next_steps.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Recommended Next Steps</h3>
            <ul className="space-y-2">
              {assessment.recommended_next_steps.map((step, idx) => (
                <li key={idx} className="text-xs text-gray-600 flex items-start gap-2">
                  <ArrowRight className="w-3 h-3 text-emerald-500 mt-0.5 flex-shrink-0" />
                  {step}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* XRF Recommendation */}
      {assessment.scanner_xrf_recommended && (
        <div className="flex items-start gap-3 p-4 bg-purple-50 border border-purple-200 rounded-xl">
          <Shield className="w-5 h-5 text-purple-600 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-purple-900">XRF Spectroscopy Recommended</p>
            <p className="text-xs text-purple-800 mt-0.5">
              For accurate material composition and grade identification, X-ray fluorescence (XRF) analysis is strongly recommended.
              Visual assessment alone cannot determine chemical composition.
            </p>
          </div>
        </div>
      )}

      {/* Processing Metadata */}
      <details className="bg-gray-50 rounded-xl border border-gray-200">
        <summary className="px-5 py-3 cursor-pointer text-sm font-medium text-gray-700 flex items-center gap-2">
          <Cpu className="w-4 h-4 text-gray-400" />
          Processing Metadata
        </summary>
        <div className="px-5 pb-4 grid grid-cols-2 sm:grid-cols-3 gap-3">
          <MetaItem label="Model" value={assessment.processing_metadata.model_used} />
          <MetaItem label="Processing Time" value={`${assessment.processing_metadata.processing_time_ms}ms`} />
          <MetaItem label="Tokens Used" value={assessment.processing_metadata.tokens_used.toString()} />
          <MetaItem label="Images" value={assessment.processing_metadata.image_count.toString()} />
          <MetaItem label="Total Size" value={`${(assessment.processing_metadata.total_image_size_bytes / 1024).toFixed(0)} KB`} />
          <MetaItem label="Validation" value={assessment.processing_metadata.validation_passed ? 'Passed' : 'Failed'} />
        </div>
      </details>
    </div>
  );
}

// --- Helper Components ---

function CollapsibleSection({
  title,
  subtitle,
  icon: Icon,
  expanded,
  onToggle,
  color,
  count,
  badge,
  children,
}: {
  title: string;
  subtitle?: string;
  icon: React.ElementType;
  expanded: boolean;
  onToggle: () => void;
  color?: 'blue' | 'amber' | 'red';
  count?: number;
  badge?: React.ReactNode;
  children: React.ReactNode;
}) {
  const iconColors = {
    blue: 'text-blue-500 bg-blue-50',
    amber: 'text-amber-500 bg-amber-50',
    red: 'text-red-500 bg-red-50',
  };

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full px-5 py-4 flex items-center justify-between hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${iconColors[color || 'blue']}`}>
            <Icon className="w-4 h-4" />
          </div>
          <div className="text-left">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
              {count !== undefined && (
                <span className="px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded text-xs">{count}</span>
              )}
              {badge}
            </div>
            {subtitle && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
          </div>
        </div>
        {expanded ? (
          <ChevronUp className="w-4 h-4 text-gray-400" />
        ) : (
          <ChevronDown className="w-4 h-4 text-gray-400" />
        )}
      </button>
      {expanded && <div className="px-5 pb-5 border-t border-gray-100 pt-4">{children}</div>}
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-2 bg-gray-50 rounded-lg">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="text-sm font-medium text-gray-900">{value}</p>
    </div>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-gray-500">{label}</p>
      <p className="text-sm font-medium text-gray-800">{value}</p>
    </div>
  );
}


