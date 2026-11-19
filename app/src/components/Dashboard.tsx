import React, { useEffect, useState } from 'react';
import {
  Activity,
  CheckCircle,
  AlertTriangle,
  XCircle,
  TrendingUp,
  FileText,
  Clock,
  ArrowRight,
} from 'lucide-react';
import { Assessment, DashboardStats } from '../types/assessment';
import { getDashboardStats, listAssessments } from '../services/assessmentService';

interface DashboardProps {
  onNavigate: (page: string) => void;
  onViewAssessment: (id: string) => void;
}

export default function Dashboard({ onNavigate, onViewAssessment }: DashboardProps) {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [assessments, setAssessments] = useState<Assessment[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      const [statsRes, assessmentsRes] = await Promise.all([
        getDashboardStats(),
        listAssessments(0, 100),
      ]);
      if (statsRes.data) setStats(statsRes.data);
      if (assessmentsRes.data) setAssessments(assessmentsRes.data);
      setLoading(false);
    }
    loadData();
  }, []);

  const getStatusBadge = (status: Assessment['status']) => {
    switch (status) {
      case 'completed':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700">
            <CheckCircle className="w-3 h-3" /> Completed
          </span>
        );
      case 'requires_review':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-700">
            <AlertTriangle className="w-3 h-3" /> Review Required
          </span>
        );
      case 'processing':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700">
            <Clock className="w-3 h-3" /> Processing
          </span>
        );
      case 'failed':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-50 text-red-700">
            <XCircle className="w-3 h-3" /> Failed
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-gray-50 text-gray-700">
            Pending
          </span>
        );
    }
  };

  const getConfidenceColor = (confidence: number) => {
    if (confidence >= 0.7) return 'text-emerald-600';
    if (confidence >= 0.4) return 'text-amber-600';
    return 'text-red-600';
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-3 border-emerald-200 border-t-emerald-600 rounded-full animate-spin"></div>
          <p className="text-sm text-gray-500">Loading dashboard...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Dashboard</h2>
          <p className="text-sm text-gray-500 mt-1">Overview of scrap material assessments</p>
        </div>
        <button
          onClick={() => onNavigate('upload')}
          className="inline-flex items-center gap-2 px-4 py-2.5 bg-emerald-600 text-white rounded-lg text-sm font-medium hover:bg-emerald-700 transition-colors shadow-sm"
        >
          <FileText className="w-4 h-4" />
          New Assessment
        </button>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={Activity}
          label="Total Assessments"
          value={stats?.total_assessments || 0}
          color="blue"
        />
        <StatCard
          icon={CheckCircle}
          label="Completed"
          value={stats?.completed || 0}
          color="emerald"
        />
        <StatCard
          icon={AlertTriangle}
          label="Pending Review"
          value={stats?.pending_review || 0}
          color="amber"
        />
        <StatCard
          icon={TrendingUp}
          label="Avg Confidence"
          value={`${Math.round((stats?.avg_confidence || 0) * 100)}%`}
          color="purple"
        />
      </div>

      {/* Recent Assessments */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-100">
          <h3 className="text-lg font-semibold text-gray-900">Recent Assessments</h3>
        </div>

        {assessments.length === 0 ? (
          <div className="px-6 py-12 text-center">
            <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <FileText className="w-8 h-8 text-gray-400" />
            </div>
            <h4 className="text-lg font-medium text-gray-900 mb-2">No assessments yet</h4>
            <p className="text-sm text-gray-500 mb-4">
              Upload scrap material images to begin your first assessment.
            </p>
            <button
              onClick={() => onNavigate('upload')}
              className="inline-flex items-center gap-2 px-4 py-2 bg-emerald-600 text-white rounded-lg text-sm font-medium hover:bg-emerald-700 transition-colors"
            >
              Start First Assessment
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {assessments.slice(0, 10).map(assessment => (
              <button
                key={assessment.assessment_id}
                onClick={() => onViewAssessment(assessment.assessment_id)}
                className="w-full px-6 py-4 flex items-center justify-between hover:bg-gray-50 transition-colors text-left"
              >
                <div className="flex items-center gap-4 min-w-0">
                  <div className="w-10 h-10 bg-gray-100 rounded-lg flex items-center justify-center flex-shrink-0">
                    <FileText className="w-5 h-5 text-gray-500" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {assessment.assessment_id}
                    </p>
                    <p className="text-xs text-gray-500 truncate">
                      {assessment.proposed_assessment?.description?.slice(0, 80) || 'Processing...'}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-4 flex-shrink-0 ml-4">
                  <span className={`text-sm font-semibold ${getConfidenceColor(assessment.confidence)}`}>
                    {Math.round(assessment.confidence * 100)}%
                  </span>
                  {getStatusBadge(assessment.status)}
                  <ArrowRight className="w-4 h-4 text-gray-400" />
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  color,
}: {
  icon: React.ElementType;
  label: string;
  value: number | string;
  color: 'blue' | 'emerald' | 'amber' | 'purple';
}) {
  const colorClasses = {
    blue: 'bg-blue-50 text-blue-600',
    emerald: 'bg-emerald-50 text-emerald-600',
    amber: 'bg-amber-50 text-amber-600',
    purple: 'bg-purple-50 text-purple-600',
  };

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <div className="flex items-center gap-3">
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${colorClasses[color]}`}>
          <Icon className="w-5 h-5" />
        </div>
        <div>
          <p className="text-2xl font-bold text-gray-900">{value}</p>
          <p className="text-xs text-gray-500">{label}</p>
        </div>
      </div>
    </div>
  );
}
