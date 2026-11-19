import React, { useEffect, useRef, useState } from 'react';
import {
  ArrowUp, Camera, Check, ChevronDown, FileAudio, FileSpreadsheet, FileText, FileVideo, Image as ImageIcon,
  Loader2, Mic, Paperclip, Plus, Square, X, FolderOpen } from 'lucide-react';
import { CopilotProviderInfo } from '../../services/copilotService';
import { useVoiceRecorder } from './useVoiceRecorder';

export type PendingKind = 'image' | 'video' | 'audio' | 'document' | 'spectrum';

export interface PendingFile {
  id: string;
  file: File;
  kind: PendingKind;
  previewUrl?: string;
}

const MB = 1024 * 1024;
export const MAX_MEDIA_BYTES = 200 * MB;
export const MAX_FILE_BYTES = 10 * MB;

export function kindOf(file: File): PendingKind {
  const t = file.type;
  const name = file.name.toLowerCase();
  if (t.startsWith('image/')) return 'image';
  if (t.startsWith('video/') || /\.(mp4|mov|m4v|avi|mkv)$/.test(name)) return 'video';
  if (t.startsWith('audio/') || /\.(mp3|wav|m4a|ogg|oga|opus|flac|aac|weba)$/.test(name)) return 'audio';
  if (/\.(xlsx|xls)$/.test(name)) return 'spectrum';
  return 'document';
}

export function toPending(files: File[]): { accepted: PendingFile[]; rejected: string[] } {
  const accepted: PendingFile[] = [];
  const rejected: string[] = [];
  for (const file of files) {
    const kind = kindOf(file);
    const limit = kind === 'video' || kind === 'audio' || file.name.toLowerCase().endsWith('.zip') ? MAX_MEDIA_BYTES : MAX_FILE_BYTES;
    if (file.size > limit) {
      rejected.push(`${file.name} is larger than ${limit / MB} MB`);
      continue;
    }
    accepted.push({
      id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      file,
      kind,
      previewUrl: kind === 'image' || kind === 'video' ? URL.createObjectURL(file) : undefined,
    });
  }
  return { accepted, rejected };
}

const KIND_ICON: Record<PendingKind, React.ElementType> = {
  image: ImageIcon, video: FileVideo, audio: FileAudio, document: FileText, spectrum: FileSpreadsheet,
};

function formatSeconds(s: number) {
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

interface ComposerProps {
  value: string;
  onChange: (v: string) => void;
  files: PendingFile[];
  onAddFiles: (files: File[]) => void;
  onRemoveFile: (id: string) => void;
  onSend: () => void;
  busy: boolean;
  providers: CopilotProviderInfo[];
  provider: string;
  onProviderChange: (name: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
}

export default function Composer({
  value, onChange, files, onAddFiles, onRemoveFile, onSend, busy, providers, provider, onProviderChange,
  placeholder = 'How can I help with your scrap, waste or minerals?', autoFocus,
}: ComposerProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const mediaInput = useRef<HTMLInputElement>(null);
  const audioInput = useRef<HTMLInputElement>(null);
  const docInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const cameraInput = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const modelRef = useRef<HTMLDivElement>(null);

  const voice = useVoiceRecorder(text => {
    onChange(value.trim() ? `${value.trim()} ${text}` : text);
    requestAnimationFrame(() => textRef.current?.focus());
  });

  // Auto-grow the textarea like a chat input.
  useEffect(() => {
    const el = textRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
  }, [value]);

  // Re-measure when the box's width changes (e.g. the stylesheet finishes loading after the first render).
  useEffect(() => {
    const el = textRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    let width = el.clientWidth;
    const ro = new ResizeObserver(() => {
      if (el.clientWidth === width) return;
      width = el.clientWidth;
      el.style.height = 'auto';
      el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => { if (autoFocus) textRef.current?.focus(); }, [autoFocus]);

  // Close popovers on outside click / Escape.
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
      if (modelRef.current && !modelRef.current.contains(e.target as Node)) setModelOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setMenuOpen(false); setModelOpen(false); } };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
  }, []);

  const pick = (ref: React.RefObject<HTMLInputElement | null>) => { setMenuOpen(false); ref.current?.click(); };
  const onPicked = (e: React.ChangeEvent<HTMLInputElement>) => {
    onAddFiles(Array.from(e.target.files ?? []));
    e.target.value = '';
  };
  const onPaste = (e: React.ClipboardEvent) => {
    const pasted = Array.from(e.clipboardData.files);
    if (pasted.length) { e.preventDefault(); onAddFiles(pasted); }
  };

  const recording = voice.state === 'recording';
  const transcribing = voice.state === 'transcribing';
  const canSend = !busy && !recording && !transcribing && (value.trim().length > 0 || files.length > 0);
  const current = providers.find(p => p.name === provider);

  return (
    <div className="w-full">
      <div className={`relative rounded-[1.4rem] border bg-white shadow-[0_2px_12px_rgba(39,37,37,0.06)] transition-colors focus-within:ring-2 focus-within:ring-ace-terracotta/40 ${
        recording ? 'border-ace-terracotta/60' : 'border-ace-line focus-within:border-ace-terracotta/50'
      }`}>
        {/* Pending attachments */}
        {files.length > 0 && (
          <div className="flex gap-2 overflow-x-auto px-3 pt-3 pb-1">
            {files.map(f => {
              const Icon = KIND_ICON[f.kind];
              return (
                <div key={f.id} className="group relative shrink-0">
                  {f.kind === 'image' && f.previewUrl ? (
                    <img src={f.previewUrl} alt={f.file.name} className="h-16 w-16 rounded-xl object-cover border border-ace-line" />
                  ) : f.kind === 'video' && f.previewUrl ? (
                    <div className="relative h-16 w-24">
                      <video src={`${f.previewUrl}#t=0.1`} muted preload="metadata" className="h-16 w-24 rounded-xl object-cover border border-ace-line bg-ace-night" />
                      <FileVideo className="absolute bottom-1 left-1 h-4 w-4 text-white drop-shadow" />
                    </div>
                  ) : (
                    <div className="flex h-16 w-44 items-center gap-2 rounded-xl border border-ace-line bg-ace-cream px-2.5">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-ace-terracotta/10">
                        <Icon className="h-4.5 w-4.5 text-ace-terracotta" />
                      </div>
                      <div className="min-w-0">
                        <p className="truncate text-xs font-medium text-ace-ink">{f.file.name}</p>
                        <p className="text-[11px] uppercase tracking-wide text-ace-muted">{f.kind}</p>
                      </div>
                    </div>
                  )}
                  <button
                    onClick={() => onRemoveFile(f.id)}
                    className="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-ace-ink text-white opacity-90 hover:opacity-100"
                    aria-label={`Remove ${f.file.name}`}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              );
            })}
          </div>
        )}

        {/* Text / recording area */}
        {recording || transcribing ? (
          <div className="flex items-center gap-3 px-4 py-4 min-h-[3.5rem]">
            {recording ? (
              <>
                <span className="h-2.5 w-2.5 rounded-full bg-ace-terracotta animate-mic-pulse" />
                <span className="font-mono text-sm text-ace-ink tabular-nums">{formatSeconds(voice.seconds)}</span>
                <div className="flex h-6 flex-1 items-center gap-[3px]" aria-hidden="true">
                  {Array.from({ length: 32 }).map((_, i) => {
                    const h = Math.max(0.12, Math.min(1, voice.level * (0.6 + 0.4 * Math.sin(i * 1.7 + voice.seconds))));
                    return <span key={i} className="w-[3px] rounded-full bg-ace-terracotta/70" style={{ height: `${h * 100}%` }} />;
                  })}
                </div>
                <span className="text-xs text-ace-muted hidden sm:inline">Listening…</span>
              </>
            ) : (
              <>
                <Loader2 className="h-4 w-4 animate-spin text-ace-terracotta" />
                <span className="text-sm text-ace-muted">Transcribing your voice locally…</span>
              </>
            )}
          </div>
        ) : (
          <textarea
            ref={textRef}
            value={value}
            rows={1}
            onChange={e => onChange(e.target.value)}
            onPaste={onPaste}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (canSend) onSend(); } }}
            placeholder={placeholder}
            aria-label="Message"
            className="block w-full resize-none bg-transparent px-4 pt-4 pb-2 text-[0.95rem] leading-6 text-ace-ink placeholder:text-ace-muted/70 focus:outline-none"
          />
        )}

        {/* Toolbar */}
        <div className="flex items-center gap-1.5 px-2.5 pb-2.5 pt-1">
          <div ref={menuRef} className="relative">
            <button
              onClick={() => setMenuOpen(o => !o)}
              disabled={recording || transcribing}
              className="flex h-11 w-11 sm:h-9 sm:w-9 items-center justify-center rounded-xl border border-ace-line text-ace-muted hover:bg-ace-cream hover:text-ace-ink disabled:opacity-40"
              aria-label="Add photos, videos, audio or files"
              aria-expanded={menuOpen}
            >
              <Plus className="h-4 w-4" />
            </button>
            {menuOpen && (
              <div className="absolute bottom-10 left-0 z-30 w-72 rounded-2xl border border-ace-line bg-white p-1.5 shadow-xl">
                {[
                  { label: 'Upload photos & videos', hint: 'JPEG, PNG, WebP, MP4, MOV', icon: ImageIcon, ref: mediaInput },
                  { label: 'Take a photo', hint: 'Use your camera', icon: Camera, ref: cameraInput },
                  { label: 'Upload audio', hint: 'Voice notes, MP3, WAV, M4A', icon: FileAudio, ref: audioInput },
                  { label: 'Upload files', hint: 'PDF, Word-like text, CSV, XLSX, JSON, MD, .pdz, ZIP', icon: Paperclip, ref: docInput },
                  { label: 'Upload a folder', hint: 'Every file inside is read', icon: FolderOpen, ref: folderInput },
                ].map(item => (
                  <button
                    key={item.label}
                    onClick={() => pick(item.ref)}
                    className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left hover:bg-ace-cream"
                  >
                    <item.icon className="h-4 w-4 text-ace-muted" />
                    <span>
                      <span className="block text-sm text-ace-ink">{item.label}</span>
                      <span className="block text-[11px] text-ace-muted">{item.hint}</span>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <input ref={mediaInput} type="file" multiple hidden accept="image/jpeg,image/png,image/webp,video/*" onChange={onPicked} />
          <input ref={cameraInput} type="file" hidden accept="image/*" capture="environment" onChange={onPicked} />
          <input ref={audioInput} type="file" multiple hidden accept="audio/*,.mp3,.wav,.m4a,.ogg,.opus,.flac,.aac" onChange={onPicked} />
          <input ref={docInput} type="file" multiple hidden accept=".pdf,.txt,.md,.csv,.tsv,.json,.xlsx,.xlsm,.xls,.pdz,.zip,.html,.htm,.xml,.log" onChange={onPicked} />
          {/* @ts-expect-error webkitdirectory is a non-standard but widely supported attribute */}
          <input ref={folderInput} type="file" multiple hidden webkitdirectory="" onChange={onPicked} />

          <div className="flex-1" />

          {/* Model picker: only when there is a real choice (a single engine is not a decision for the user) */}
          {providers.filter(p => p.configured).length > 1 && (
          <div ref={modelRef} className="relative">
            <button
              onClick={() => setModelOpen(o => !o)}
              disabled={!providers.length}
              className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs text-ace-muted hover:bg-ace-cream hover:text-ace-ink"
              aria-label="Choose AI model"
              aria-expanded={modelOpen}
            >
              <span className="max-w-[9rem] truncate sm:max-w-none">{current?.display_name ?? 'Model'}</span>
              <ChevronDown className="h-3.5 w-3.5" />
            </button>
            {modelOpen && (
              <div className="absolute bottom-9 right-0 z-30 w-72 rounded-2xl border border-ace-line bg-white p-1.5 shadow-xl">
                {providers.map(p => (
                  <button
                    key={p.name}
                    disabled={!p.configured}
                    onClick={() => { onProviderChange(p.name); setModelOpen(false); }}
                    className="flex w-full items-start gap-2 rounded-xl px-3 py-2 text-left hover:bg-ace-cream disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <span className="flex-1">
                      <span className="block text-sm text-ace-ink">{p.display_name}</span>
                      <span className="block text-[11px] text-ace-muted">
                        {p.configured ? p.model : 'Not available'}
                      </span>
                    </span>
                    {p.name === provider && <Check className="mt-0.5 h-4 w-4 text-ace-terracotta" />}
                  </button>
                ))}
              </div>
            )}
          </div>
          )}

          {/* Microphone */}
          {recording ? (
            <>
              <button onClick={voice.cancel} className="rounded-lg px-2 py-1.5 text-xs text-ace-muted hover:bg-ace-cream" aria-label="Cancel recording">
                Cancel
              </button>
              <button
                onClick={voice.stop}
                className="flex h-11 w-11 sm:h-9 sm:w-9 items-center justify-center rounded-xl bg-ace-ink text-white hover:bg-ace-night"
                aria-label="Stop recording and transcribe"
              >
                <Square className="h-3.5 w-3.5 fill-current" />
              </button>
            </>
          ) : (
            <button
              onClick={voice.start}
              disabled={busy || transcribing || voice.state === 'requesting'}
              title={voice.supported ? 'Dictate with your voice' : 'Microphone not supported in this browser'}
              className="flex h-11 w-11 sm:h-9 sm:w-9 items-center justify-center rounded-xl text-ace-muted hover:bg-ace-cream hover:text-ace-ink disabled:opacity-40"
              aria-label="Dictate with microphone"
            >
              {voice.state === 'requesting' || transcribing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mic className="h-4 w-4" />}
            </button>
          )}

          {/* Send */}
          <button
            onClick={onSend}
            disabled={!canSend}
            className="flex h-11 w-11 sm:h-9 sm:w-9 items-center justify-center rounded-xl bg-ace-terracotta text-white transition-colors hover:bg-ace-terracotta-dark disabled:bg-ace-terracotta/35"
            aria-label="Send message"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {voice.error && (
        <div className="mt-2 flex items-start gap-2 rounded-xl bg-red-50 px-3 py-2 text-xs text-red-700" role="alert">
          <span className="flex-1">{voice.error}</span>
          <button onClick={voice.dismissError} aria-label="Dismiss"><X className="h-3.5 w-3.5" /></button>
        </div>
      )}
    </div>
  );
}
