import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AudioLines, Battery, Camera, FileBarChart, ImagePlus, RotateCcw, ShieldCheck, Square, Upload, WifiOff, X } from 'lucide-react';
import {
  CopilotAttachment, CopilotChatResponse, CopilotProviderInfo, copilotAttachmentUrl, getCopilotSession, listCopilotProviders,
  friendlyError, sendCopilotMessage,
} from '../../services/copilotService';
import BrandMark from './BrandMark';
import Composer, { PendingFile, toPending } from './Composer';
import VoiceMode from './VoiceMode';
import { AssistantMessage, ChatMessage, DisplayAttachment, ThinkingIndicator, UserMessage } from './MessageView';

// Starting points in plain words, most common job first (black mass). "fill" puts an example in the box to edit.
const SUGGESTIONS = [
  { icon: Battery, label: 'Check a black-mass reading', fill: 'Ni 31.8 Co 9.1 Mn 9.5 Fe 0.4 Cu 1.2 Al 1.5' },
  { icon: Camera, label: 'Read a photo of the XRF screen', attach: true },
  { icon: FileBarChart, label: 'Compare bags & make a report', prompt: 'Compare all the readings in this chat and make a Word report' },
  { icon: ImagePlus, label: 'What can you do?', prompt: 'What can you do?' },
];
const WELCOME_KEY = 'scraptrust.welcome.dismissed';

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}

function toDisplay(sessionId: string, a: CopilotAttachment, localUrl?: string): DisplayAttachment {
  const hasPreview = a.kind === 'image' || a.kind === 'video' || a.kind === 'audio';
  return {
    id: a.attachment_id,
    kind: a.kind,
    name: a.filename,
    url: localUrl ?? (hasPreview ? copilotAttachmentUrl(sessionId, a.attachment_id) : undefined),
    text: a.text,
    source: a.source,
    note: a.note,
  };
}

interface ChatAppProps {
  sessionId: string | null;
  onSessionCreated: (id: string) => void;
  onActivity: () => void;
}

export default function ChatApp({ sessionId, onSessionCreated, onActivity }: ChatAppProps) {
  const [providers, setProviders] = useState<CopilotProviderInfo[]>([]);
  const [provider, setProvider] = useState('');
  const [categories, setCategories] = useState<string[]>([]);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [files, setFiles] = useState<PendingFile[]>([]);
  const [busy, setBusy] = useState(false);
  const [busyLabel, setBusyLabel] = useState('Thinking…');
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [voiceMode, setVoiceMode] = useState(false);
  const [hint, setHint] = useState<string | null>(null);
  const [online, setOnline] = useState(typeof navigator === 'undefined' ? true : navigator.onLine);
  const [failed, setFailed] = useState<{ message: string; files: PendingFile[] } | null>(null);
  const [welcome, setWelcome] = useState(() => { try { return !localStorage.getItem(WELCOME_KEY); } catch { return true; } });
  const abortRef = useRef<AbortController | null>(null);

  const activeId = useRef<string | null>(null);    // session this view currently shows
  const turnCount = useRef(0);                     // stored turns in that session
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener('online', up);
    window.addEventListener('offline', down);
    return () => { window.removeEventListener('online', up); window.removeEventListener('offline', down); };
  }, []);

  const dismissWelcome = () => { setWelcome(false); try { localStorage.setItem(WELCOME_KEY, '1'); } catch { /* private mode */ } };

  useEffect(() => {
    listCopilotProviders()
      .then(r => { setProviders(r.providers); setProvider(r.default); setCategories(r.waste_categories ?? []); })
      .catch(e => setBackendError(friendlyError(e)));
  }, []);

  // Open the selected conversation (or start fresh).
  useEffect(() => {
    if (sessionId === activeId.current) return;
    activeId.current = sessionId;
    setFiles([]);
    setNotice(null);
    if (!sessionId) { setMessages([]); turnCount.current = 0; return; }
    setLoading(true);
    getCopilotSession(sessionId)
      .then(s => {
        if (activeId.current !== sessionId) return;
        const msgs: ChatMessage[] = s.turns.map((t, idx) => {
          if (t.role === 'user') {
            const atts = t.attachment_ids.map(id => s.attachments[id]).filter(Boolean).map(a => toDisplay(s.session_id, a));
            const voiceOnly = /^please respond to the attached voice message\.?$/i.test(t.text);
            return { key: `${s.session_id}-${idx}`, role: 'user', text: t.text, attachments: atts, voiceOnly };
          }
          const question = s.turns[idx - 1];
          const hasImage = !!question?.attachment_ids.some(id => s.attachments[id]?.kind === 'image');
          return {
            key: `${s.session_id}-${idx}`, role: 'assistant', text: t.text, toolCalls: t.tool_calls ?? [],
            provider: t.provider, model: t.model, turnIndex: idx, hasImage, feedback: t.feedback ?? null,
            verification: t.verification,
            files: (t.generated ?? []).map(id => s.attachments[id]).filter(Boolean).map(a => ({ id: a.attachment_id, name: a.filename, size: a.size_bytes })),
          };
        });
        setMessages(msgs);
        turnCount.current = s.turns.length;
      })
      .catch(e => setMessages([{ key: 'load-error', role: 'error', text: `Couldn't open this conversation: ${e.message}` }]))
      .finally(() => setLoading(false));
  }, [sessionId]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }, [messages, busy]);

  const addFiles = useCallback((incoming: File[]) => {
    const { accepted, rejected } = toPending(incoming);
    setFiles(f => [...f, ...accepted]);
    setNotice(rejected.length ? rejected.join('; ') : null);
  }, []);

  const send = async (text?: string): Promise<CopilotChatResponse | null> => {
    const message = (text ?? input).trim();
    if ((!message && !files.length) || busy) return null;
    const pending = files;
    const voiceOnly = !message && pending.length > 0 && pending.every(p => p.kind === 'audio');

    setMessages(m => [...m, {
      key: `local-${Date.now()}`,
      role: 'user',
      text: message,
      voiceOnly,
      attachments: pending.map(p => ({ id: p.id, kind: p.kind, name: p.file.name, url: p.previewUrl ?? (p.kind === 'audio' ? URL.createObjectURL(p.file) : undefined) })),
    }]);
    setInput('');
    setFiles([]);
    setNotice(null);
    setFailed(null);
    setHint(null);
    setBusy(true);
    const controller = new AbortController();
    abortRef.current = controller;
    setBusyLabel(
      pending.some(p => p.kind === 'audio' || p.kind === 'video') ? 'Transcribing and analysing…'
        : pending.some(p => p.kind === 'image') ? 'Analysing your photos…'
          : pending.length ? 'Reading your files…' : 'Thinking…'
    );

    try {
      const res = await sendCopilotMessage({ message, files: pending.map(p => p.file), sessionId: activeId.current, provider, signal: controller.signal });
      const isNew = activeId.current !== res.session_id;
      activeId.current = res.session_id;
      if (isNew) onSessionCreated(res.session_id);

      // Map server attachments (ids, transcripts, video frames) onto the optimistic message.
      const originals = res.attachments.filter(a => !a.source);
      const display = res.attachments.map(a => {
        const i = originals.indexOf(a);
        const local = i >= 0 ? pending[i] : undefined;
        return toDisplay(res.session_id, a, local?.previewUrl);
      });
      const turnIndex = turnCount.current + 1;
      turnCount.current += 2;
      setMessages(m => {
        const copy = [...m];
        const last = copy[copy.length - 1];
        if (last?.role === 'user') copy[copy.length - 1] = { ...last, attachments: display };
        return [...copy, {
          key: `a-${res.session_id}-${turnIndex}`, role: 'assistant', text: res.reply, toolCalls: res.tool_calls,
          provider: res.provider, model: res.model, turnIndex, hasImage: res.attachments.some(a => a.kind === 'image'),
          verification: res.verification,
          files: (res.generated_files ?? []).map(f => ({ id: f.attachment_id, name: f.filename, size: f.size_bytes })),
        }];
      });
      onActivity();
      return res;
    } catch (e) {
      const stopped = e instanceof Error && e.message === 'STOPPED';
      setMessages(m => [...m, {
        key: `err-${Date.now()}`, role: 'error',
        text: stopped ? 'Stopped. If the answer was nearly ready it may still appear when you reopen this conversation.' : friendlyError(e),
      }]);
      setFailed({ message, files: pending });
      return null;
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length) addFiles(Array.from(e.dataTransfer.files));
  };

  // Phones: Talk sits in the normal flow above the message box (a floating button would cover content)
  const mobileTalk = (
    <button onClick={() => setVoiceMode(true)}
            className="mb-2 flex min-h-[44px] w-full items-center justify-center gap-2 rounded-xl border border-ace-line bg-white/80 text-sm text-ace-ink sm:hidden">
      <AudioLines className="h-4 w-4 text-ace-terracotta" /> Talk hands-free
    </button>
  );

  const composer = (hero: boolean) => (
    <Composer
      value={input}
      onChange={setInput}
      files={files}
      onAddFiles={addFiles}
      onRemoveFile={id => setFiles(f => f.filter(x => x.id !== id))}
      onSend={() => send()}
      busy={busy}
      providers={providers}
      provider={provider}
      onProviderChange={setProvider}
      autoFocus={hero}
      placeholder={hero ? 'Type XRF numbers (e.g. Ni 31.8 Co 9.1) or ask a question…' : 'Reply to ScrapTrust…'}
    />
  );

  const retry = () => {
    if (!failed || busy) return;
    setFiles(failed.files);
    const msg = failed.message;
    setFailed(null);
    setTimeout(() => send(msg), 0);
  };

  const privacyLine = (
    <p className="mt-2 flex items-center justify-center gap-1 text-center text-[11px] text-ace-muted/90">
      <ShieldCheck className="h-3 w-3 shrink-0" />
      Your messages and files are saved to your Library and kept by ACE Green to check and improve ScrapTrust. Don't upload personal information.
    </p>
  );

  const empty = messages.length === 0 && !loading;

  return (
    <div
      className="relative flex h-full flex-col"
      onDragOver={e => { e.preventDefault(); setDragging(true); }}
      onDragLeave={e => { if (e.currentTarget === e.target) setDragging(false); }}
      onDrop={onDrop}
    >
      {dragging && (
        <div className="pointer-events-none absolute inset-3 z-40 flex items-center justify-center rounded-3xl border-2 border-dashed border-ace-terracotta/60 bg-ace-cream/90">
          <div className="flex flex-col items-center gap-2 text-ace-terracotta">
            <Upload className="h-8 w-8" />
            <p className="text-sm font-medium">Drop photos, videos, audio or files</p>
          </div>
        </div>
      )}

      {voiceMode && (
        <VoiceMode
          onClose={() => setVoiceMode(false)}
          ask={async text => { const r = await send(text); return r ? (r.speech || r.reply) : null; }}
        />
      )}

      <button
        onClick={() => setVoiceMode(true)}
        title="Hands-free voice conversation: talk, and ScrapTrust answers out loud"
        className="absolute right-4 top-3 z-30 hidden items-center gap-1.5 sm:flex rounded-full border border-ace-line bg-white/80 px-3 py-1.5 text-sm text-ace-ink shadow-sm transition-colors hover:border-ace-terracotta/50 hover:bg-white"
      >
        <AudioLines className="h-4 w-4 text-ace-terracotta" /> Talk
      </button>

      {!online && (
        <div className="mx-auto mt-3 w-full max-w-3xl px-4" role="status">
          <div className="flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900">
            <WifiOff className="h-4 w-4 shrink-0" /> You're offline. Messages can't be sent until your connection is back.
          </div>
        </div>
      )}

      {backendError && (
        <div className="mx-auto mt-3 w-full max-w-3xl px-4">
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{backendError}</div>
        </div>
      )}

      {empty ? (
        <div className="flex flex-1 flex-col items-center justify-start overflow-y-auto px-4 pb-16 pt-16 sm:justify-center sm:pt-0">
          <div className="mb-8 flex items-center gap-3">
            <BrandMark size={40} tile={false} />
            <h1 className="text-3xl font-normal tracking-tight text-ace-ink sm:text-[2.6rem]">{greeting()}</h1>
          </div>
          <div className="w-full max-w-2xl">
            {welcome && (
              <div className="relative mb-4 rounded-2xl border border-ace-line bg-white/80 p-4 pr-12 text-sm text-ace-ink" role="note">
                <button onClick={dismissWelcome} className="absolute right-1 top-1 rounded-full p-3 text-ace-muted hover:bg-ace-stone" aria-label="Close welcome">
                  <X className="h-4 w-4" />
                </button>
                <p className="mb-1 font-medium">Welcome to ScrapTrust</p>
                <ol className="list-decimal space-y-0.5 pl-5 text-ace-muted">
                  <li><strong className="text-ace-ink">Type</strong> your XRF gun numbers, or press <strong className="text-ace-ink">+</strong> to add a photo of the gun screen or the gun's file.</li>
                  <li>ScrapTrust tells you the <strong className="text-ace-ink">battery type</strong> and <strong className="text-ace-ink">estimates</strong> nickel, cobalt, manganese and lithium.</li>
                  <li>Everything is kept in your <strong className="text-ace-ink">Library</strong>. Estimates are a guide: confirm with a lab test before you buy or sell.</li>
                </ol>
              </div>
            )}
            {mobileTalk}
            {composer(true)}
            {notice && <p className="mt-2 text-xs text-red-600">{notice}</p>}
            {hint && <p className="mt-2 rounded-lg bg-ace-stone/70 px-3 py-1.5 text-xs text-ace-ink" role="status">{hint}</p>}
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map(s => (
                <button
                  key={s.label}
                  onClick={() => {
                    if (s.fill) { setInput(s.fill); setHint('Example reading added: change the numbers to yours, then press send.'); }
                    else if (s.attach) { setHint('Press + below, then choose "Take a photo" or "Upload photos & videos" and pick the picture of the XRF screen.'); }
                    else if (s.prompt) send(s.prompt);
                  }}
                  disabled={busy}
                  className="flex min-h-[44px] items-center gap-1.5 rounded-full border border-ace-line bg-white/60 px-3.5 py-2 text-sm text-ace-ink/80 transition-colors hover:border-ace-terracotta/40 hover:bg-white hover:text-ace-ink"
                >
                  <s.icon className="h-4 w-4" /> {s.label}
                </button>
              ))}
            </div>
            <p className="mt-6 text-center text-xs text-ace-muted">
              Type, talk, or press <strong>+</strong> to add photos, XRF files, documents, voice notes or videos.
            </p>
            {privacyLine}
          </div>
        </div>
      ) : (
        <>
          <div ref={scrollRef} className="flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-3xl space-y-7 px-4 py-8">
              {loading && <ThinkingIndicator label="Opening conversation…" />}
              {messages.map(m =>
                m.role === 'user'
                  ? <UserMessage key={m.key} message={m} />
                  : <AssistantMessage key={m.key} message={m} sessionId={activeId.current} categories={categories} />
              )}
              {busy && (
                <div className="flex flex-wrap items-center gap-3">
                  <ThinkingIndicator label={busyLabel} />
                  <button onClick={() => abortRef.current?.abort()}
                          className="inline-flex min-h-[40px] items-center gap-1.5 rounded-full border border-ace-line bg-white px-3 py-1.5 text-xs text-ace-ink hover:bg-ace-stone">
                    <Square className="h-3.5 w-3.5" /> Stop
                  </button>
                </div>
              )}
              {failed && !busy && (
                <button onClick={retry}
                        className="ml-9 inline-flex min-h-[40px] items-center gap-1.5 rounded-full bg-ace-terracotta px-4 py-1.5 text-sm text-white hover:opacity-90">
                  <RotateCcw className="h-4 w-4" /> Try again
                </button>
              )}
            </div>
          </div>
          <div className="bg-gradient-to-t from-ace-cream via-ace-cream to-transparent pt-2">
            <div className="mx-auto w-full max-w-3xl px-4 pb-4">
              {mobileTalk}
              {composer(false)}
              {notice && <p className="mt-2 text-xs text-red-600">{notice}</p>}
            {hint && <p className="mt-2 rounded-lg bg-ace-stone/70 px-3 py-1.5 text-xs text-ace-ink" role="status">{hint}</p>}
              <p className="mt-2 text-center text-[11px] text-ace-muted">
                ScrapTrust gives estimates and can make mistakes. Confirm composition with a lab test before you buy or sell.
              </p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
