import React, { useCallback, useEffect, useState } from 'react';
import AppShell, { Page } from './components/AppShell';
import ChatApp from './components/chat/ChatApp';
import Dashboard from './components/Dashboard';
import UploadPage from './components/UploadPage';
import AssessmentResults from './components/AssessmentResults';
import LibraryPage from './components/LibraryPage';
import RecordsPage from './components/RecordsPage';
import HelpPage from './components/HelpPage';
import { Assessment } from './types/assessment';
import { getAssessment } from './services/assessmentService';
import { CopilotSessionSummary, deleteCopilotSession, listCopilotSessions } from './services/copilotService';

export default function App({ username, role, recordsVisible, onSignOut }: { username?: string; role?: string; recordsVisible?: boolean; onSignOut?: () => void } = {}) {
  const isAdmin = role === 'admin';
  const canSeeRecords = isAdmin || !!recordsVisible;
  const [page, setPage] = useState<Page>('chat');
  const [currentAssessment, setCurrentAssessment] = useState<Assessment | null>(null);
  const [sessions, setSessions] = useState<CopilotSessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [chatKey, setChatKey] = useState(0);   // remount the chat for "New chat"

  const refreshSessions = useCallback(() => {
    listCopilotSessions().then(setSessions).catch(() => undefined);
  }, []);

  useEffect(() => { refreshSessions(); }, [refreshSessions]);

  const newChat = () => {
    setActiveSessionId(null);
    setChatKey(k => k + 1);
    setPage('chat');
  };

  const openSession = (id: string) => {
    setActiveSessionId(id);
    setPage('chat');
  };

  const deleteSession = async (id: string) => {
    try {
      await deleteCopilotSession(id);
    } finally {
      if (id === activeSessionId) newChat();
      refreshSessions();
    }
  };

  const handleViewAssessment = async (id: string) => {
    const response = await getAssessment(id);
    if (response.success && response.data) {
      setCurrentAssessment(response.data);
      setPage('results');
    }
  };

  const renderPage = () => {
    switch (page) {
      case 'chat':
        return (
          <ChatApp
            key={chatKey}
            sessionId={activeSessionId}
            onSessionCreated={id => { setActiveSessionId(id); refreshSessions(); }}
            onActivity={refreshSessions}
          />
        );
      case 'library':
        return <LibraryPage onOpenConversation={openSession} />;
      case 'help':
        return <HelpPage />;
      case 'records':
        return canSeeRecords ? <RecordsPage readOnly={!isAdmin} /> : null;
      case 'dashboard':
        return <Dashboard onNavigate={p => setPage(p as Page)} onViewAssessment={handleViewAssessment} />;
      case 'upload':
        return <UploadPage onAssessmentComplete={a => { setCurrentAssessment(a); setPage('results'); }} />;
      case 'results':
        return currentAssessment ? (
          <AssessmentResults
            assessment={currentAssessment}
            onBack={() => setPage('dashboard')}
            onNewAssessment={() => setPage('upload')}
          />
        ) : (
          <div className="py-12 text-center">
            <p className="text-ace-muted">No assessment selected.</p>
            <button onClick={() => setPage('dashboard')} className="mt-4 text-sm font-medium text-ace-terracotta">
              Go to Assessments
            </button>
          </div>
        );
    }
  };

  return (
    <AppShell
      page={page}
      onNavigate={setPage}
      sessions={sessions}
      activeSessionId={activeSessionId}
      onSelectSession={openSession}
      onNewChat={newChat}
      onDeleteSession={deleteSession}
      username={username}
      isAdmin={canSeeRecords}
      recordsLabel={isAdmin ? 'Records (admin)' : 'Records'}
      onSignOut={onSignOut}
    >
      {renderPage()}
    </AppShell>
  );
}
