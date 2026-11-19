import React, { useState } from 'react';
import { ClipboardList, Database, FilePlus2, HelpCircle, Library, LogOut, Menu, MessageSquare, PanelLeftClose, PanelLeftOpen, Plus, Trash2, X } from 'lucide-react';
import { CopilotSessionSummary } from '../services/copilotService';
import BrandMark from './chat/BrandMark';

export type Page = 'chat' | 'dashboard' | 'upload' | 'results' | 'library' | 'records' | 'help';

interface AppShellProps {
  page: Page;
  onNavigate: (page: Page) => void;
  sessions: CopilotSessionSummary[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onDeleteSession: (id: string) => void;
  username?: string;
  isAdmin?: boolean;
  recordsLabel?: string;
  onSignOut?: () => void;
  children: React.ReactNode;
}

function groupLabel(iso: string): string {
  const d = new Date(iso);
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  if (days < 1 && new Date().getDate() === d.getDate()) return 'Today';
  if (days < 2) return 'Yesterday';
  if (days < 7) return 'Previous 7 days';
  if (days < 30) return 'Previous 30 days';
  return 'Older';
}

export default function AppShell({
  page, onNavigate, sessions, activeSessionId, onSelectSession, onNewChat, onDeleteSession, username, isAdmin, recordsLabel, onSignOut, children,
}: AppShellProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  const go = (fn: () => void) => { fn(); setMobileOpen(false); };

  const groups: { label: string; items: CopilotSessionSummary[] }[] = [];
  for (const s of sessions) {
    const label = groupLabel(s.updated_at || s.created_at);
    const g = groups.find(x => x.label === label);
    if (g) g.items.push(s); else groups.push({ label, items: [s] });
  }

  const navItem = (id: Page, label: string, Icon: React.ElementType, onClick: () => void) => (
    <button
      onClick={() => go(onClick)}
      title={label}
      className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors ${
        page === id ? 'bg-ace-stone text-ace-ink' : 'text-ace-muted hover:bg-ace-stone/70 hover:text-ace-ink'
      } ${collapsed ? 'justify-center' : ''}`}
    >
      <Icon className="h-4 w-4 shrink-0" />
      {!collapsed && <span className="truncate">{label}</span>}
    </button>
  );

  const sidebar = (mobile: boolean) => {
    const narrow = collapsed && !mobile;
    return (
      <div className={`flex h-full flex-col bg-ace-sand ${narrow ? 'w-[60px]' : 'w-[272px]'} transition-[width] duration-200`}>
        <div className={`flex items-center gap-2 px-3 pb-2 pt-3 ${narrow ? 'flex-col' : ''}`}>
          <button onClick={() => go(onNewChat)} className="flex items-center gap-2.5 rounded-lg p-1 hover:bg-ace-stone/70" title="ScrapTrust home">
            <BrandMark size={28} />
            {!narrow && (
              <span className="text-left leading-tight">
                <span className="block text-[0.95rem] font-semibold text-ace-ink">ScrapTrust</span>
                <span className="block text-[11px] text-ace-muted">by ACE Green Recycling</span>
              </span>
            )}
          </button>
          <div className="flex-1" />
          {mobile ? (
            <button onClick={() => setMobileOpen(false)} className="rounded-lg p-2.5 text-ace-muted hover:bg-ace-stone" aria-label="Close menu">
              <X className="h-4.5 w-4.5" />
            </button>
          ) : (
            <button
              onClick={() => setCollapsed(c => !c)}
              className="rounded-lg p-1.5 text-ace-muted hover:bg-ace-stone"
              aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              {collapsed ? <PanelLeftOpen className="h-4.5 w-4.5" /> : <PanelLeftClose className="h-4.5 w-4.5" />}
            </button>
          )}
        </div>

        <div className="space-y-0.5 px-2">
          <button
            onClick={() => go(onNewChat)}
            title="New chat"
            className={`mb-1 flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium text-ace-terracotta hover:bg-ace-stone/70 ${narrow ? 'justify-center' : ''}`}
          >
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-ace-terracotta text-white">
              <Plus className="h-3.5 w-3.5" />
            </span>
            {!narrow && 'New chat'}
          </button>
          {navItem('chat', 'Chats', MessageSquare, () => onNavigate('chat'))}
          {navItem('library', 'Library', Library, () => onNavigate('library'))}
          {navItem('dashboard', 'Assessments', ClipboardList, () => onNavigate('dashboard'))}
          {navItem('upload', 'New assessment', FilePlus2, () => onNavigate('upload'))}
          {isAdmin && navItem('records', recordsLabel || 'Records (admin)', Database, () => onNavigate('records'))}
          {navItem('help', 'Help', HelpCircle, () => onNavigate('help'))}
        </div>

        {!narrow && (
          <div className="mt-4 flex-1 overflow-y-auto px-2 pb-3">
            {sessions.length === 0 ? (
              <p className="px-2.5 text-xs text-ace-muted/80">Your conversations will appear here.</p>
            ) : (
              groups.map(g => (
                <div key={g.label} className="mb-3">
                  <p className="px-2.5 pb-1 text-[11px] font-medium uppercase tracking-wide text-ace-muted/80">{g.label}</p>
                  {g.items.map(s => (
                    <div
                      key={s.session_id}
                      className={`group flex items-center rounded-lg ${
                        s.session_id === activeSessionId && page === 'chat' ? 'bg-ace-stone' : 'hover:bg-ace-stone/70'
                      }`}
                    >
                      <button
                        onClick={() => go(() => onSelectSession(s.session_id))}
                        className="min-w-0 flex-1 truncate px-2.5 py-1.5 text-left text-sm text-ace-ink"
                        title={s.title}
                      >
                        {s.title}
                      </button>
                      <button
                        onClick={() => { if (window.confirm(`Delete "${s.title}"? This can't be undone.`)) onDeleteSession(s.session_id); }}
                        className="mr-1 rounded p-1 text-ace-muted opacity-0 hover:text-red-600 focus:opacity-100 group-hover:opacity-100"
                        aria-label={`Delete conversation ${s.title}`}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              ))
            )}
          </div>
        )}
        {narrow && <div className="flex-1" />}

        {onSignOut && (
          <div className={`border-t border-ace-line px-2 py-2 ${narrow ? 'flex justify-center' : 'flex items-center gap-2'}`}>
            {!narrow && <span className="min-w-0 flex-1 truncate px-1 text-xs text-ace-muted" title={username}>{username}</span>}
            <button onClick={onSignOut} title="Sign out" aria-label="Sign out"
              className="rounded-lg p-1.5 text-ace-muted hover:bg-ace-stone/70 hover:text-ace-ink">
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        )}
        {!narrow && (
          <div className="border-t border-ace-line px-4 py-3 text-[11px] leading-4 text-ace-muted">
            Scrap, waste, recycling &amp; mineral analysis. Answers can be wrong; verify grades with XRF or lab tests.
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="flex h-[100dvh] overflow-hidden bg-ace-cream">
      {/* Desktop sidebar */}
      <aside className="hidden border-r border-ace-line md:block print:hidden">{sidebar(false)}</aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-ace-night/40" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 shadow-2xl">{sidebar(true)}</aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile top bar */}
        <div className="flex items-center gap-2 border-b border-ace-line px-3 py-2 md:hidden print:hidden">
          <button onClick={() => setMobileOpen(true)} className="rounded-lg p-2.5 text-ace-muted hover:bg-ace-stone" aria-label="Open menu">
            <Menu className="h-5 w-5" />
          </button>
          <BrandMark size={24} />
          <span className="text-sm font-semibold text-ace-ink">ScrapTrust</span>
          <div className="flex-1" />
          <button onClick={onNewChat} className="rounded-lg p-2.5 text-ace-terracotta hover:bg-ace-stone" aria-label="New chat">
            <Plus className="h-5 w-5" />
          </button>
        </div>

        <main className={`min-h-0 flex-1 ${page === 'chat' ? '' : 'overflow-y-auto'}`}>
          {page === 'chat' ? children : <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">{children}</div>}
        </main>
      </div>
    </div>
  );
}
