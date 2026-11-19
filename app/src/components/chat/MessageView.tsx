import React, { useState } from 'react';
import {
  AlertTriangle, Check, ChevronDown, ChevronRight, Copy, Download, FileAudio, FileSpreadsheet, FileText, Mic, ShieldCheck, ThumbsDown, ThumbsUp, Wrench, X,
} from 'lucide-react';
import { AttachmentKind, CopilotToolCall, CopilotVerification, copilotAttachmentUrl, sendCopilotFeedback } from '../../services/copilotService';
import BrandMark from './BrandMark';
import Markdown from './Markdown';

export interface DisplayAttachment {
  id: string;
  kind: AttachmentKind;
  name: string;
  url?: string;          // preview / playback URL
  text?: string | null;  // transcript or extracted text
  source?: string | null;
  note?: string | null;
}

export interface ChatMessage {
  key: string;
  role: 'user' | 'assistant' | 'error';
  text: string;
  attachments?: DisplayAttachment[];
  toolCalls?: CopilotToolCall[];
  provider?: string;
  model?: string;
  turnIndex?: number;
  hasImage?: boolean;
  feedback?: { rating: 'up' | 'down'; corrected_category?: string | null } | null;
  voiceOnly?: boolean;
  verification?: CopilotVerification;
  files?: { id: string; name: string; size?: number }[];   // agent-generated downloads
}

const TOOL_LABELS: Record<string, string> = {
  identify_material: 'Material identification',
  analyze_waste_image: 'Dataset similarity',
  assess_image_quality: 'Evidence quality',
  get_waste_cluster_profile: 'Cluster profile',
  get_waste_dataset_overview: 'Dataset overview',
  interpret_mineral_spectrum: 'Mineral spectrum',
  get_mineral_model_info: 'Mineral model',
  search_knowledge_base: 'Knowledge base',
  assess_black_mass_xrf: 'Black-mass assessment',
  get_black_mass_model_info: 'Black-mass models',
  analyse_lot: 'Lot-analyst agent',
  write_assessment_report: 'Report-writer agent',
};

function Downloads({ files, sessionId }: { files: { id: string; name: string; size?: number }[]; sessionId: string | null }) {
  if (!files.length || !sessionId) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {files.map(f => (
        <a key={f.id} href={copilotAttachmentUrl(sessionId, f.id)} download={f.name}
           className="flex items-center gap-2 rounded-xl border border-ace-terracotta/40 bg-white px-3 py-2 text-sm text-ace-ink shadow-sm transition-colors hover:bg-ace-terracotta/10">
          <Download className="h-4 w-4 text-ace-terracotta" />
          <span className="font-medium">{f.name}</span>
          {f.size ? <span className="text-xs text-ace-muted">{Math.max(1, Math.round(f.size / 1024))} KB</span> : null}
        </a>
      ))}
    </div>
  );
}

function VerificationBadge({ v }: { v?: CopilotVerification }) {
  if (!v || !v.numbers_checked) return null;
  if (v.status === 'verified')
    return (
      <span title="The answer-checker agent traced every composition number in this answer to measured or model data."
            className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700">
        <ShieldCheck className="h-3 w-3" /> {v.numbers_checked} number{v.numbers_checked === 1 ? '' : 's'} checked{v.repaired ? ' (corrected)' : ''}
      </span>
    );
  if (v.status === 'unverified_numbers')
    return (
      <span title={v.ungrounded.map(u => u.context).join('\n')}
            className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-800">
        <AlertTriangle className="h-3 w-3" /> {v.ungrounded.length} number{v.ungrounded.length === 1 ? '' : 's'} not traceable to data
      </span>
    );
  return (
    <span title="No data tool was used: numbers come from general knowledge."
          className="inline-flex items-center gap-1 rounded-full bg-ace-line/40 px-2 py-0.5 text-[11px] text-ace-muted">
      General knowledge, not from your data
    </span>
  );
}

// --------------------------------------------------------------------------- user message
function UserAttachments({ items }: { items: DisplayAttachment[] }) {
  const originals = items.filter(a => !a.source);
  const frames = items.filter(a => a.source);
  if (!originals.length) return null;
  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex flex-wrap justify-end gap-2">
        {originals.map(a => {
          if (a.kind === 'image')
            return a.url ? (
              <a key={a.id} href={a.url} target="_blank" rel="noreferrer">
                <img src={a.url} alt={a.name} className="h-28 w-28 rounded-xl object-cover border border-ace-line sm:h-36 sm:w-36" />
              </a>
            ) : null;
          if (a.kind === 'video')
            return (
              <div key={a.id} className="w-64 max-w-full">
                {a.url && <video src={a.url} controls preload="metadata" className="aspect-video w-full rounded-xl border border-ace-line bg-ace-night" />}
                <p className="mt-1 truncate text-right text-[11px] text-ace-muted">{a.name}</p>
              </div>
            );
          if (a.kind === 'audio')
            return (
              <div key={a.id} className="w-72 max-w-full rounded-xl border border-ace-line bg-white p-2">
                <div className="mb-1.5 flex items-center gap-1.5 text-xs text-ace-muted">
                  <FileAudio className="h-3.5 w-3.5" /> <span className="truncate">{a.name}</span>
                </div>
                {a.url && <audio src={a.url} controls preload="metadata" className="h-8 w-full" />}
              </div>
            );
          const Icon = a.kind === 'spectrum' ? FileSpreadsheet : FileText;
          return (
            <div key={a.id} className="flex w-56 items-center gap-2.5 rounded-xl border border-ace-line bg-white px-3 py-2">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-ace-terracotta/10">
                <Icon className="h-4 w-4 text-ace-terracotta" />
              </div>
              <div className="min-w-0">
                <p className="truncate text-xs font-medium text-ace-ink">{a.name}</p>
                <p className="text-[11px] uppercase tracking-wide text-ace-muted">{a.kind}</p>
              </div>
            </div>
          );
        })}
      </div>
      {frames.length > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] text-ace-muted">{frames.length} frames analysed</span>
          {frames.map(f => f.url && <img key={f.id} src={f.url} alt={f.name} className="h-8 w-8 rounded-md object-cover border border-ace-line" />)}
        </div>
      )}
    </div>
  );
}

function Transcripts({ items }: { items: DisplayAttachment[] }) {
  const spoken = items.filter(a => (a.kind === 'audio' || a.kind === 'video') && !a.source);
  if (!spoken.length) return null;
  return (
    <div className="space-y-1.5">
      {spoken.map(a => (
        <div key={a.id} className="max-w-full rounded-xl bg-white/70 px-3 py-2 text-xs text-ace-muted">
          <span className="mb-0.5 flex items-center gap-1 font-medium text-ace-ink"><Mic className="h-3 w-3" /> Transcript</span>
          {a.text ? <span className="italic">“{a.text}”</span> : <span>{a.note || 'Transcribing on send…'}</span>}
        </div>
      ))}
    </div>
  );
}

export function UserMessage({ message }: { message: ChatMessage }) {
  const atts = message.attachments ?? [];
  return (
    <div className="flex flex-col items-end gap-2">
      <UserAttachments items={atts} />
      {message.text && !message.voiceOnly && (
        <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl bg-ace-stone px-4 py-2.5 text-[0.95rem] leading-6 text-ace-ink">
          {message.text}
        </div>
      )}
      <div className="max-w-[85%]"><Transcripts items={atts} /></div>
    </div>
  );
}

// --------------------------------------------------------------------------- assistant message
function ToolChip({ calls }: { calls: CopilotToolCall[] }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<number | null>(null);
  if (!calls.length) return null;
  const errors = calls.filter(c => c.is_error).length;
  return (
    <div className="mb-3">
      <button
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-1.5 rounded-full border border-ace-line bg-white px-3 py-1 text-xs text-ace-muted hover:text-ace-ink"
        aria-expanded={open}
      >
        <Wrench className="h-3.5 w-3.5" />
        Used {calls.length} analysis tool{calls.length > 1 ? 's' : ''}
        {errors > 0 && <span className="text-red-600">· {errors} failed</span>}
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
      </button>
      {open && (
        <ul className="mt-2 space-y-1.5">
          {calls.map((c, idx) => (
            <li key={idx} className="text-xs">
              <button
                onClick={() => setDetail(detail === idx ? null : idx)}
                className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left ${
                  c.is_error ? 'bg-red-50 text-red-700' : 'bg-ace-stone/70 text-ace-ink hover:bg-ace-stone'
                }`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${c.is_error ? 'bg-red-500' : 'bg-ace-green'}`} />
                <span className="font-medium">{TOOL_LABELS[c.name] ?? c.name}</span>
                <span className="truncate text-ace-muted">{JSON.stringify(c.input)}</span>
                <span className="ml-auto shrink-0 text-ace-muted">{c.duration_ms} ms</span>
              </button>
              {detail === idx && (
                <pre className="mt-1 max-h-72 overflow-auto rounded-lg bg-ace-night p-2.5 font-mono text-[11px] text-ace-stone">
                  {JSON.stringify(c.output, null, 2)}
                </pre>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function predictedCategory(calls?: CopilotToolCall[]): string | null {
  const call = calls?.find(c => c.name === 'analyze_waste_image' && !c.is_error);
  const out = call?.output as { status?: string; neighbour_category_votes?: { category: string }[] } | undefined;
  return out?.status === 'ok' ? out.neighbour_category_votes?.[0]?.category ?? null : null;
}

function Actions({ message, sessionId, categories }: { message: ChatMessage; sessionId: string | null; categories: string[] }) {
  const [copied, setCopied] = useState(false);
  const [rating, setRating] = useState<'up' | 'down' | null>(message.feedback?.rating ?? null);
  const [saved, setSaved] = useState<string | null>(
    message.feedback ? `Feedback saved${message.feedback.corrected_category ? ` · verified as "${message.feedback.corrected_category}"` : ''}` : null
  );
  const [correcting, setCorrecting] = useState(false);
  const [category, setCategory] = useState('');
  const [note, setNote] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const canReview = sessionId !== null && message.turnIndex !== undefined;

  const copy = async () => {
    try { await navigator.clipboard.writeText(message.text); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* clipboard blocked */ }
  };
  const submit = async (r: 'up' | 'down', corrected?: string | null) => {
    if (!canReview) return;
    setRating(r);
    setErr(null);
    try {
      const res = await sendCopilotFeedback(sessionId!, { turn_index: message.turnIndex!, rating: r, corrected_category: corrected || null, note: note || null });
      setCorrecting(false);
      setSaved(
        (res.labels_recorded ? `Saved as ${res.labels_recorded} reviewed label${res.labels_recorded > 1 ? 's' : ''}` : 'Feedback saved')
        + (corrected ? ` · verified as "${corrected}"` : '')
      );
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };
  const btn = 'flex h-7 w-7 items-center justify-center rounded-md hover:bg-ace-stone';

  return (
    <div className="mt-2">
      <div className="flex items-center gap-0.5 text-ace-muted">
        <button onClick={copy} className={btn} aria-label="Copy answer" title="Copy">
          {copied ? <Check className="h-3.5 w-3.5 text-ace-green" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
        {canReview && !saved && (
          <>
            <button onClick={() => submit('up', predictedCategory(message.toolCalls))} className={`${btn} ${rating === 'up' ? 'text-ace-terracotta' : ''}`} aria-label="Good answer" title="Good answer">
              <ThumbsUp className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={() => { setRating('down'); if (message.hasImage) setCorrecting(true); else submit('down'); }}
              className={`${btn} ${rating === 'down' ? 'text-ace-terracotta' : ''}`}
              aria-label="Bad answer"
              title="Bad answer"
            >
              <ThumbsDown className="h-3.5 w-3.5" />
            </button>
            {message.hasImage && !correcting && (
              <button onClick={() => setCorrecting(true)} className="ml-1 rounded-md px-1.5 py-1 text-xs hover:bg-ace-stone hover:text-ace-ink">
                Correct the category
              </button>
            )}
          </>
        )}
        {saved && <span className="ml-1 flex items-center gap-1 text-xs text-ace-slate"><Check className="h-3.5 w-3.5" />{saved}</span>}
        {message.provider && message.provider !== "offline" && <span className="ml-auto text-[11px]" title={message.model}>Answered by {message.provider}</span>}
      </div>
      {correcting && (
        <div className="mt-2 flex flex-wrap items-center gap-2 rounded-xl border border-ace-line bg-white p-2 text-xs">
          <span className="text-ace-muted">This is actually</span>
          <select value={category} onChange={e => setCategory(e.target.value)} className="rounded-lg border border-ace-line bg-white px-2 py-1" aria-label="Correct category">
            <option value="">choose…</option>
            {categories.map(c => <option key={c} value={c}>{c}</option>)}
            <option value="other / mixed">other / mixed</option>
          </select>
          <input value={note} onChange={e => setNote(e.target.value)} placeholder="note (optional)" maxLength={300}
            className="min-w-[8rem] flex-1 rounded-lg border border-ace-line px-2 py-1" />
          <button onClick={() => submit(rating ?? 'down', category)} disabled={!category}
            className="rounded-lg bg-ace-terracotta px-3 py-1 text-white disabled:opacity-40">Save</button>
          <button onClick={() => setCorrecting(false)} className="text-ace-muted hover:text-ace-ink" aria-label="Cancel"><X className="h-3.5 w-3.5" /></button>
        </div>
      )}
      {err && <p className="mt-1 text-xs text-red-600">{err}</p>}
    </div>
  );
}

export function AssistantMessage({ message, sessionId, categories }: { message: ChatMessage; sessionId: string | null; categories: string[] }) {
  if (message.role === 'error') {
    return (
      <div className="flex gap-3">
        <div className="mt-0.5"><BrandMark size={26} /></div>
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{message.text}</div>
      </div>
    );
  }
  return (
    <div className="flex gap-3">
      <div className="mt-0.5"><BrandMark size={26} /></div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <ToolChip calls={message.toolCalls ?? []} />
          <VerificationBadge v={message.verification} />
        </div>
        <Markdown text={message.text} />
        <Downloads files={message.files ?? []} sessionId={sessionId} />
        <Actions message={message} sessionId={sessionId} categories={categories} />
      </div>
    </div>
  );
}

export function ThinkingIndicator({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3">
      <BrandMark size={26} />
      <div className="flex items-center gap-2 text-sm text-ace-muted">
        <span className="flex gap-1">
          <span className="typing-dot h-1.5 w-1.5 rounded-full bg-ace-terracotta" />
          <span className="typing-dot h-1.5 w-1.5 rounded-full bg-ace-terracotta" />
          <span className="typing-dot h-1.5 w-1.5 rounded-full bg-ace-terracotta" />
        </span>
        {label}
      </div>
    </div>
  );
}
