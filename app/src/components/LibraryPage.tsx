import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AudioLines, Battery, Check, Download, FileText, FlaskConical, Image as ImageIcon, Library, MessageSquare, Pencil, Pin, PinOff,
  ScanLine, Search, Trash2, Video, X,
} from 'lucide-react';
import {
  LibraryItem, LibraryKind, libraryDownloadUrl, listLibrary, openLibraryItem, removeLibraryItem, updateLibraryItem,
} from '../services/recordsService';

const KINDS: { id: LibraryKind | null; label: string }[] = [
  { id: null, label: 'All' },
  { id: 'assessment', label: 'Assessments' },
  { id: 'report', label: 'Reports' },
  { id: 'xrf', label: 'XRF files' },
  { id: 'document', label: 'Documents' },
  { id: 'image', label: 'Photos' },
  { id: 'audio', label: 'Voice notes' },
  { id: 'video', label: 'Videos' },
  { id: 'spectrum', label: 'Spectra' },
];

const ICONS: Record<LibraryKind, React.ElementType> = {
  assessment: Battery, report: FileText, xrf: ScanLine, document: FileText, image: ImageIcon,
  audio: AudioLines, video: Video, spectrum: FlaskConical,
};

function when(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) + ' · '
    + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

function size(bytes: number): string {
  if (!bytes) return '';
  return bytes > 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function Downloads({ item }: { item: LibraryItem }) {
  const link = (format: 'txt' | 'pdf' | 'original', label: string) => (
    <a href={libraryDownloadUrl(item.item_id, format)} download
       className="inline-flex items-center gap-1 rounded-lg border border-ace-line bg-white px-2.5 py-1 text-xs text-ace-ink hover:border-ace-terracotta/50 hover:bg-ace-terracotta/5">
      <Download className="h-3.5 w-3.5 text-ace-terracotta" /> {label}
    </a>
  );
  return (
    <div className="flex flex-wrap gap-1.5">
      {link('txt', 'Text')}
      {link('pdf', 'PDF')}
      {item.attachment_id && item.kind !== 'assessment' && link('original', 'Original')}
    </div>
  );
}

function ItemCard({ item, onChange, onOpen, onRemoved }: { item: LibraryItem; onChange: (i: LibraryItem) => void; onOpen: (i: LibraryItem) => void; onRemoved: (id: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(item.title);
  const [error, setError] = useState<string | null>(null);
  const Icon = ICONS[item.kind] ?? FileText;

  const save = async () => {
    const t = title.trim();
    if (!t || t === item.title) { setEditing(false); setTitle(item.title); return; }
    try { onChange(await updateLibraryItem(item.item_id, { title: t })); setEditing(false); setError(null); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  const remove = async () => {
    if (!window.confirm(`Remove "${item.title}" from your Library? The conversation it came from is not deleted.`)) return;
    try { await removeLibraryItem(item.item_id); onRemoved(item.item_id); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  const togglePin = async () => {
    try { onChange(await updateLibraryItem(item.item_id, { pinned: !item.pinned })); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

  return (
    <div className={`group flex flex-col gap-2 rounded-2xl border bg-white/70 p-4 transition-colors hover:bg-white ${item.pinned ? 'border-ace-terracotta/40' : 'border-ace-line'}`}>
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-ace-stone text-ace-terracotta">
          <Icon className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          {editing ? (
            <div className="flex items-center gap-1">
              <input autoFocus value={title} maxLength={200} onChange={e => setTitle(e.target.value)}
                     onKeyDown={e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') { setEditing(false); setTitle(item.title); } }}
                     className="w-full rounded-md border border-ace-line px-2 py-1 text-sm outline-none focus:border-ace-terracotta" aria-label="New name" />
              <button onClick={save} title="Save name" className="rounded p-1 text-emerald-700 hover:bg-emerald-50"><Check className="h-4 w-4" /></button>
              <button onClick={() => { setEditing(false); setTitle(item.title); }} title="Cancel" className="rounded p-1 text-ace-muted hover:bg-ace-stone"><X className="h-4 w-4" /></button>
            </div>
          ) : (
            <button onClick={() => onOpen(item)} className="block w-full truncate text-left text-sm font-medium text-ace-ink hover:text-ace-terracotta" title={item.title}>
              {item.title}
            </button>
          )}
          <p className="mt-0.5 text-[11px] text-ace-muted">{when(item.created_at)}{item.size_bytes ? ` · ${size(item.size_bytes)}` : ''}</p>
        </div>
        <div className="flex shrink-0 gap-0.5">
          <button onClick={togglePin} title={item.pinned ? 'Unpin' : 'Pin to top'}
                  className={`rounded-md p-2.5 sm:p-1.5 ${item.pinned ? 'text-ace-terracotta' : 'text-ace-muted opacity-60 group-hover:opacity-100'} hover:bg-ace-stone`}>
            {item.pinned ? <PinOff className="h-4 w-4" /> : <Pin className="h-4 w-4" />}
          </button>
          <button onClick={() => setEditing(true)} title="Rename" className="rounded-md p-2.5 sm:p-1.5 text-ace-muted opacity-60 hover:bg-ace-stone group-hover:opacity-100">
            <Pencil className="h-4 w-4" />
          </button>
          <button onClick={remove} title="Remove from Library" className="rounded-md p-2.5 sm:p-1.5 text-ace-muted opacity-60 hover:bg-ace-stone hover:text-red-700 group-hover:opacity-100">
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>
      {item.preview && <p className="line-clamp-2 whitespace-pre-line text-xs text-ace-muted">{item.preview}</p>}
      {error && <p className="text-xs text-red-600">{error}</p>}
      <Downloads item={item} />
    </div>
  );
}

function Viewer({ item, onClose, onOpenConversation }: { item: LibraryItem; onClose: () => void; onOpenConversation: (id: string) => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={onClose} role="dialog" aria-label={item.title}>
      <div className="flex max-h-[85vh] w-full max-w-3xl flex-col rounded-2xl bg-ace-cream shadow-xl" onClick={e => e.stopPropagation()}>
        <div className="flex items-start gap-3 border-b border-ace-line p-4">
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-base font-medium text-ace-ink">{item.title}</h2>
            <p className="text-xs text-ace-muted">{item.kind} · {when(item.created_at)}{item.filename && item.filename !== item.title ? ` · ${item.filename}` : ''}</p>
          </div>
          <button onClick={onClose} className="rounded-full p-1.5 text-ace-muted hover:bg-ace-stone" title="Close"><X className="h-5 w-5" /></button>
        </div>
        <pre className="flex-1 overflow-auto whitespace-pre-wrap p-4 font-mono text-xs leading-relaxed text-ace-ink">
          {item.text || 'No text content for this item. Download the original file to view it.'}
        </pre>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-ace-line p-3">
          <Downloads item={item} />
          {item.session_id && (
            <button onClick={() => onOpenConversation(item.session_id!)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-ace-terracotta px-3 py-1.5 text-xs font-medium text-white hover:opacity-90">
              <MessageSquare className="h-3.5 w-3.5" /> Open conversation
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function LibraryPage({ onOpenConversation }: { onOpenConversation: (sessionId: string) => void }) {
  const [q, setQ] = useState('');
  const [kind, setKind] = useState<LibraryKind | null>(null);
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewing, setViewing] = useState<LibraryItem | null>(null);
  const timer = useRef<number | null>(null);

  const load = useCallback((query: string, k: LibraryKind | null, append = false, offset = 0) => {
    setLoading(true);
    listLibrary(query, k, offset)
      .then(r => { setItems(prev => (append ? [...prev, ...r.items] : r.items)); setTotal(r.total); setError(null); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => load(q.trim(), kind), 250);
    return () => { if (timer.current) window.clearTimeout(timer.current); };
  }, [q, kind, load]);

  const replace = (i: LibraryItem) => {
    setItems(prev => {
      const next = prev.map(x => (x.item_id === i.item_id ? { ...x, ...i, preview: x.preview } : x));
      return [...next.filter(x => x.pinned), ...next.filter(x => !x.pinned)];
    });
  };

  const open = async (i: LibraryItem) => {
    try { setViewing(await openLibraryItem(i.item_id)); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

  const pinned = items.filter(i => i.pinned);
  const rest = items.filter(i => !i.pinned);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-5xl px-4 py-8">
        <div className="mb-5 flex items-center gap-3">
          <Library className="h-6 w-6 text-ace-terracotta" />
          <h1 className="text-2xl font-normal text-ace-ink">Library</h1>
          <span className="text-sm text-ace-muted">{total} item{total === 1 ? '' : 's'}</span>
        </div>
        <div className="relative mb-3">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ace-muted" />
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search your files, reports and assessments…" maxLength={100}
                 className="w-full rounded-xl border border-ace-line bg-white py-2.5 pl-9 pr-3 text-sm outline-none focus:border-ace-terracotta" aria-label="Search library" />
        </div>
        <div className="mb-6 flex flex-wrap gap-1.5">
          {KINDS.map(k => (
            <button key={k.label} onClick={() => setKind(k.id)}
                    className={`rounded-full border px-3 py-1 text-xs transition-colors ${kind === k.id ? 'border-ace-terracotta bg-ace-terracotta text-white' : 'border-ace-line bg-white/60 text-ace-muted hover:text-ace-ink'}`}>
              {k.label}
            </button>
          ))}
        </div>

        {error && <p className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{error}</p>}
        {!loading && items.length === 0 && !error && (
          <div className="rounded-2xl border border-dashed border-ace-line p-10 text-center text-sm text-ace-muted">
            {q || kind ? 'Nothing matches your search.' : 'Everything you upload, every assessment and every report you create will appear here.'}
          </div>
        )}

        {pinned.length > 0 && (
          <>
            <h2 className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-ace-muted"><Pin className="h-3.5 w-3.5" /> Pinned</h2>
            <div className="mb-6 grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
              {pinned.map(i => <ItemCard key={i.item_id} item={i} onChange={replace} onOpen={open} onRemoved={id => { setItems(p => p.filter(x => x.item_id !== id)); setTotal(t => t - 1); }} />)}
            </div>
          </>
        )}
        {rest.length > 0 && (
          <>
            {pinned.length > 0 && <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-ace-muted">All items</h2>}
            <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
              {rest.map(i => <ItemCard key={i.item_id} item={i} onChange={replace} onOpen={open} onRemoved={id => { setItems(p => p.filter(x => x.item_id !== id)); setTotal(t => t - 1); }} />)}
            </div>
          </>
        )}
        {items.length < total && (
          <div className="mt-6 text-center">
            <button onClick={() => load(q.trim(), kind, true, items.length)} disabled={loading}
                    className="rounded-full border border-ace-line bg-white px-4 py-1.5 text-sm text-ace-ink hover:bg-ace-stone disabled:opacity-50">
              {loading ? 'Loading…' : 'Show more'}
            </button>
          </div>
        )}
      </div>
      {viewing && <Viewer item={viewing} onClose={() => setViewing(null)} onOpenConversation={id => { setViewing(null); onOpenConversation(id); }} />}
    </div>
  );
}
