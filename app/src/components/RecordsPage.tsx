import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { BrainCircuit, CalendarDays, ChevronLeft, Database, Download, FlaskConical, Search, ShieldAlert, X } from 'lucide-react';
import {
  ActivityEvent, CalendarCounts, LearningRun, Observation, clearObservationIcp, learningStatus, recordsActions, recordsActivity,
  recordsCalendar, recordsEvent, recordsExportUrl, recordsObservations, setObservationIcp,
} from '../services/recordsService';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const ICP_ELEMENTS = ['Ni', 'Co', 'Mn', 'Fe', 'Cu', 'Al', 'P', 'Li'];
const pad = (n: number) => String(n).padStart(2, '0');
const time = (ts: number) => new Date(ts * 1000).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' });

function heat(n: number, max: number): string {
  if (!n) return 'bg-white/50 text-ace-muted/60';
  const r = n / Math.max(max, 1);
  return r > 0.66 ? 'bg-ace-terracotta text-white' : r > 0.33 ? 'bg-ace-terracotta/60 text-white' : 'bg-ace-terracotta/20 text-ace-ink';
}

// ---------------------------------------------------------------- calendar (year -> month -> day)
function Calendar({ period, onPeriod }: { period: string; onPeriod: (p: string) => void }) {
  const [years, setYears] = useState<Record<string, number>>({});
  const [data, setData] = useState<CalendarCounts | null>(null);
  const year = period ? Number(period.slice(0, 4)) : undefined;
  const month = period.length >= 7 ? Number(period.slice(5, 7)) : undefined;

  useEffect(() => { recordsCalendar().then(r => setYears(r.counts)).catch(() => undefined); }, []);
  useEffect(() => {
    if (!year) { setData(null); return; }
    recordsCalendar(year, month).then(setData).catch(() => setData(null));
  }, [year, month]);

  const yearList = Array.from(new Set([...Object.keys(years), String(new Date().getFullYear())])).sort();
  const max = data ? Math.max(0, ...Object.values(data.counts)) : 0;

  return (
    <div className="rounded-2xl border border-ace-line bg-white/60 p-3">
      <div className="mb-2 flex items-center gap-1.5 text-sm font-medium text-ace-ink">
        <CalendarDays className="h-4 w-4 text-ace-terracotta" />
        {month && year ? (
          <button onClick={() => onPeriod(String(year))} className="inline-flex items-center gap-1 hover:text-ace-terracotta"><ChevronLeft className="h-4 w-4" />{MONTHS[month - 1]} {year}</button>
        ) : year ? (
          <button onClick={() => onPeriod('')} className="inline-flex items-center gap-1 hover:text-ace-terracotta"><ChevronLeft className="h-4 w-4" />{year}</button>
        ) : 'All time'}
      </div>
      {!year && (
        <div className="grid grid-cols-3 gap-1.5">
          {yearList.map(y => (
            <button key={y} onClick={() => onPeriod(y)} className={`rounded-lg px-2 py-2 text-xs ${heat(years[y] || 0, Math.max(...Object.values(years), 1))}`}>
              <div className="font-medium">{y}</div><div>{years[y] || 0}</div>
            </button>
          ))}
        </div>
      )}
      {year && !month && (
        <div className="grid grid-cols-3 gap-1.5">
          {MONTHS.map((m, i) => {
            const n = data?.counts[`${year}-${pad(i + 1)}`] || 0;
            return (
              <button key={m} onClick={() => onPeriod(`${year}-${pad(i + 1)}`)} className={`rounded-lg px-2 py-2 text-xs ${heat(n, max)}`}>
                <div className="font-medium">{m}</div><div>{n}</div>
              </button>
            );
          })}
        </div>
      )}
      {year && month && (() => {
        const first = new Date(year, month - 1, 1).getDay();          // 0 = Sunday
        const days = new Date(year, month, 0).getDate();
        const selectedDay = period.length === 10 ? period : '';
        return (
          <div className="grid grid-cols-7 gap-1 text-center text-[11px]">
            {['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((d, i) => <div key={i} className="text-ace-muted">{d}</div>)}
            {Array.from({ length: first }).map((_, i) => <div key={`e${i}`} />)}
            {Array.from({ length: days }).map((_, i) => {
              const key = `${year}-${pad(month)}-${pad(i + 1)}`;
              const n = data?.counts[key] || 0;
              return (
                <button key={key} onClick={() => onPeriod(selectedDay === key ? `${year}-${pad(month)}` : key)} title={`${n} event(s)`}
                        className={`rounded-md py-1.5 ${heat(n, max)} ${selectedDay === key ? 'ring-2 ring-ace-ink' : ''}`}>
                  {i + 1}
                </button>
              );
            })}
          </div>
        );
      })()}
    </div>
  );
}

// ---------------------------------------------------------------- activity
function EventDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const [ev, setEv] = useState<ActivityEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { recordsEvent(id).then(setEv).catch(e => setError(e.message)); }, [id]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={onClose} role="dialog" aria-label="Event detail">
      <div className="flex max-h-[85vh] w-full max-w-3xl flex-col rounded-2xl bg-ace-cream shadow-xl" onClick={e => e.stopPropagation()}>
        <div className="flex items-start gap-3 border-b border-ace-line p-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-medium text-ace-ink">{ev ? ev.action : 'Loading…'}</h2>
            {ev && <p className="text-xs text-ace-muted">#{ev.id} · {time(ev.ts)} · {ev.username || 'anonymous'}{ev.session_id ? ` · conversation ${ev.session_id.slice(0, 8)}` : ''}</p>}
          </div>
          <button onClick={onClose} className="rounded-full p-1.5 text-ace-muted hover:bg-ace-stone" title="Close"><X className="h-5 w-5" /></button>
        </div>
        <div className="flex-1 overflow-auto p-4">
          {error && <p className="text-sm text-red-600">{error}</p>}
          {ev && <p className="mb-3 whitespace-pre-wrap text-sm text-ace-ink">{ev.summary}</p>}
          {ev?.detail !== undefined && ev?.detail !== null && (
            <pre className="whitespace-pre-wrap break-words rounded-xl bg-white p-3 font-mono text-[11px] leading-relaxed text-ace-ink">{JSON.stringify(ev.detail, null, 2)}</pre>
          )}
        </div>
      </div>
    </div>
  );
}

function ActivityTab({ period }: { period: string }) {
  const [q, setQ] = useState('');
  const [user, setUser] = useState('');
  const [action, setAction] = useState('');
  const [actions, setActions] = useState<string[]>([]);
  const [items, setItems] = useState<ActivityEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => { recordsActions().then(r => setActions(r.actions)).catch(() => undefined); }, []);
  const load = useCallback((offset = 0) => {
    recordsActivity({ period: period || undefined, q, username: user, action, offset })
      .then(r => { setItems(prev => (offset ? [...prev, ...r.items] : r.items)); setTotal(r.total); setError(null); })
      .catch(e => setError(e.message));
  }, [period, q, user, action]);
  useEffect(() => { const t = window.setTimeout(() => load(0), 250); return () => window.clearTimeout(t); }, [load]);

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ace-muted" />
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search everything: messages, readings, files, users…" maxLength={200}
                 className="w-full rounded-xl border border-ace-line bg-white py-2 pl-9 pr-3 text-sm outline-none focus:border-ace-terracotta" aria-label="Search activity" />
        </div>
        <input value={user} onChange={e => setUser(e.target.value)} placeholder="User" maxLength={64}
               className="w-32 rounded-xl border border-ace-line bg-white px-3 py-2 text-sm outline-none focus:border-ace-terracotta" aria-label="Filter by user" />
        <select value={action} onChange={e => setAction(e.target.value)} aria-label="Filter by action"
                className="rounded-xl border border-ace-line bg-white px-3 py-2 text-sm outline-none focus:border-ace-terracotta">
          <option value="">All activity</option>
          {actions.map(a => <option key={a} value={a}>{a}</option>)}
        </select>
      </div>
      <div className="mb-2 flex items-center justify-between text-xs text-ace-muted">
        <span>{total} event{total === 1 ? '' : 's'}{period ? ` in ${period}` : ''}</span>
        <span className="flex gap-1.5">
          {(['jsonl', 'csv'] as const).map(f => (
            <a key={f} href={recordsExportUrl(period || undefined, f)} download
               className="inline-flex items-center gap-1 rounded-lg border border-ace-line bg-white px-2 py-1 text-ace-ink hover:bg-ace-stone">
              <Download className="h-3.5 w-3.5 text-ace-terracotta" /> Export {f.toUpperCase()}
            </a>
          ))}
        </span>
      </div>
      {error && <p className="mb-2 text-sm text-red-600">{error}</p>}
      <div className="divide-y divide-ace-line overflow-hidden rounded-2xl border border-ace-line bg-white/70">
        {items.map(ev => (
          <button key={ev.id} onClick={() => setOpen(ev.id)} className="flex w-full flex-wrap items-center gap-x-3 gap-y-0.5 px-3 py-2 text-left text-sm hover:bg-white">
            <span className="w-28 shrink-0 text-[11px] text-ace-muted">{time(ev.ts)}</span>
            <span className="w-20 shrink-0 truncate text-xs text-ace-ink" title={ev.username || ''}>{ev.username || '—'}</span>
            <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] ${ev.action.startsWith('security:') || ev.action.startsWith('admin:') ? 'bg-amber-50 text-amber-800' : 'bg-ace-stone text-ace-ink'}`}>{ev.action}</span>
            <span className="min-w-0 basis-full truncate text-xs text-ace-muted 2xl:basis-0 2xl:flex-1">{ev.summary}</span>
          </button>
        ))}
        {items.length === 0 && <p className="p-6 text-center text-sm text-ace-muted">No activity{period ? ' in this period' : ''}.</p>}
      </div>
      {items.length < total && (
        <div className="mt-3 text-center"><button onClick={() => load(items.length)} className="rounded-full border border-ace-line bg-white px-4 py-1.5 text-sm hover:bg-ace-stone">Show more</button></div>
      )}
      {open !== null && <EventDetail id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

// ---------------------------------------------------------------- readings (observations) + lab labels
function IcpForm({ obs, onSaved, onCancel }: { obs: Observation; onSaved: (o: Observation) => void; onCancel: () => void }) {
  const [vals, setVals] = useState<Record<string, string>>({});
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    const values: Record<string, number> = {};
    for (const [k, v] of Object.entries(vals)) if (v.trim() !== '') values[k] = Number(v);
    if (!Object.keys(values).length || Object.values(values).some(v => Number.isNaN(v))) { setError('Enter the lab wt% values as numbers.'); return; }
    if (note.trim().length < 3) { setError('Enter the lab report number so this result can be traced.'); return; }
    try { onSaved(await setObservationIcp(obs.id, values, note)); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <div className="mt-2 rounded-xl border border-ace-terracotta/30 bg-white p-3">
      <p className="mb-2 text-xs text-ace-muted">Enter this sample's <strong>lab (ICP-OES) result</strong> in wt%. Only real lab results: this reading then becomes training data for self-learning.</p>
      <div className="grid grid-cols-4 gap-2 sm:grid-cols-8">
        {ICP_ELEMENTS.map(e => (
          <label key={e} className="text-[11px] text-ace-muted">{e}
            <input inputMode="decimal" value={vals[e] ?? ''} onChange={ev => setVals(v => ({ ...v, [e]: ev.target.value }))}
                   className="mt-0.5 w-full rounded-md border border-ace-line px-1.5 py-1 text-xs text-ace-ink outline-none focus:border-ace-terracotta" />
          </label>
        ))}
      </div>
      <input value={note} onChange={e => setNote(e.target.value)} placeholder="Lab report number (required)" maxLength={500}
             className="mt-2 w-full rounded-md border border-ace-line px-2 py-1 text-xs outline-none focus:border-ace-terracotta" />
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
      <div className="mt-2 flex gap-2">
        <button onClick={save} className="rounded-lg bg-ace-terracotta px-3 py-1 text-xs font-medium text-white hover:opacity-90">Save lab result</button>
        <button onClick={onCancel} className="rounded-lg border border-ace-line px-3 py-1 text-xs text-ace-muted hover:text-ace-ink">Cancel</button>
      </div>
    </div>
  );
}

function ReadingsTab({ period, readOnly }: { period: string; readOnly?: boolean }) {
  const [state, setState] = useState('');
  const [items, setItems] = useState<Observation[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [editing, setEditing] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    recordsObservations({ period: period || undefined, state: state || undefined })
      .then(r => { setItems(r.items); setCounts(r.counts); setError(null); }).catch(e => setError(e.message));
  }, [period, state]);
  useEffect(load, [load]);
  const fmt = (o: Record<string, number> | null | undefined, keys: string[]) =>
    keys.filter(k => o && o[k] !== undefined).map(k => `${k} ${Number(o![k]).toFixed(2)}`).join(' · ') || '—';

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
        {['', 'UNLABELLED', 'CONFIRMED'].map(s => (
          <button key={s} onClick={() => setState(s)}
                  className={`rounded-full border px-3 py-1 ${state === s ? 'border-ace-terracotta bg-ace-terracotta text-white' : 'border-ace-line bg-white/60 text-ace-muted'}`}>
            {s ? `${s.toLowerCase()} (${counts[s] || 0})` : 'All readings'}
          </button>
        ))}
        <span className="text-ace-muted">Every black-mass reading anyone assessed, in structured form.</span>
      </div>
      {error && <p className="mb-2 text-sm text-red-600">{error}</p>}
      <div className="space-y-2">
        {items.map(o => (
          <div key={o.id} className="rounded-2xl border border-ace-line bg-white/70 p-3 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-ace-muted">{time(o.ts)}</span>
              <span className="text-ace-ink">{o.username}</span>
              <span className="font-medium text-ace-ink">{o.label}</span>
              <span className="text-ace-muted">{o.instrument} · {o.basis}</span>
              <span className="rounded-full bg-ace-stone px-2 py-0.5">{o.material || 'UNKNOWN'}{o.compound ? ` · ${o.compound.split(' (')[0]}` : ''}</span>
              <span className={`ml-auto rounded-full px-2 py-0.5 ${o.label_state === 'CONFIRMED' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800'}`}>
                {o.label_state === 'CONFIRMED' ? 'lab-confirmed' : 'no lab result'}
              </span>
            </div>
            <div className="mt-1.5 grid gap-0.5 text-ace-muted">
              <span><strong className="text-ace-ink">Gun (observed):</strong> {fmt(o.observed, ['Ni', 'Co', 'Mn', 'Fe', 'Cu', 'Al', 'P'])}</span>
              <span><strong className="text-ace-ink">Model (inferred):</strong> {fmt(o.results?.values, ['Ni', 'Co', 'Mn', 'Li'])}</span>
              {o.icp && <span><strong className="text-ace-ink">Lab ICP:</strong> {fmt(o.icp, ICP_ELEMENTS)} {o.icp_by ? `(by ${o.icp_by}${o.icp_note ? `, ${o.icp_note}` : ''})` : ''}</span>}
            </div>
            <div className="mt-2 flex gap-2">
              {!readOnly && o.label_state === 'UNLABELLED' && editing !== o.id && (
                <button onClick={() => setEditing(o.id)} className="inline-flex items-center gap-1 rounded-lg border border-ace-line bg-white px-2 py-1 hover:bg-ace-stone">
                  <FlaskConical className="h-3.5 w-3.5 text-ace-terracotta" /> Add lab result
                </button>
              )}
              {!readOnly && o.label_state === 'CONFIRMED' && (
                <button onClick={async () => { await clearObservationIcp(o.id).catch(() => undefined); load(); }}
                        className="rounded-lg border border-ace-line bg-white px-2 py-1 text-ace-muted hover:text-ace-ink">Remove lab result</button>
              )}
            </div>
            {editing === o.id && <IcpForm obs={o} onCancel={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />}
          </div>
        ))}
        {items.length === 0 && <p className="rounded-2xl border border-dashed border-ace-line p-6 text-center text-sm text-ace-muted">No readings{period ? ' in this period' : ''}.</p>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- self-learning
function LearningTab() {
  const [runs, setRuns] = useState<LearningRun[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  useEffect(() => { learningStatus().then(r => { setRuns(r.runs); setCounts(r.observations); }).catch(() => undefined); }, []);
  return (
    <div className="space-y-4 text-sm">
      <div className="grid gap-3 sm:grid-cols-3">
        {[['Readings recorded', (counts.UNLABELLED || 0) + (counts.CONFIRMED || 0)], ['With lab result (training data)', counts.CONFIRMED || 0],
          ['Without lab result (never trained on)', counts.UNLABELLED || 0]].map(([l, n]) => (
          <div key={String(l)} className="rounded-2xl border border-ace-line bg-white/70 p-4">
            <div className="text-2xl font-medium text-ace-ink">{n}</div><div className="text-xs text-ace-muted">{l}</div>
          </div>
        ))}
      </div>
      <div className="rounded-2xl border border-ace-line bg-white/70 p-4 text-xs leading-relaxed text-ace-muted">
        <p className="mb-1 font-medium text-ace-ink">How the models improve themselves</p>
        Each night (housekeeping <code>--learn</code>) a candidate model is retrained on the original reference samples plus every reading that has a
        lab result. It is tested on the original samples held out one at a time and is <strong>only kept as a candidate if it is clearly better</strong>
        (average error at least 2 % lower, no element more than 10 % worse, lithium and the material detector not worse). A person then reviews it and makes it live with <code>python -m src.realmodels.learning --activate &lt;stamp&gt;</code>; the previous model is backed up and every model file is checksum-verified before use.
        Readings without a lab result are recorded but never used to train, so the model never learns from its own guesses.
      </div>
      <div className="overflow-hidden rounded-2xl border border-ace-line bg-white/70">
        {runs.map(r => (
          <div key={r.id} className="flex flex-wrap items-center gap-3 border-b border-ace-line px-3 py-2 text-xs last:border-0">
            <span className="w-36 text-ace-muted">{time(r.ts)}</span>
            <span className={`rounded-full px-2 py-0.5 ${r.promoted ? 'bg-emerald-50 text-emerald-700' : 'bg-ace-stone text-ace-ink'}`}>{r.status}</span>
            <span className="text-ace-muted">{r.confirmed_rows} lab-confirmed</span>
            <span className="min-w-0 flex-1 truncate text-ace-muted" title={r.note}>{r.note}</span>
          </div>
        ))}
        {runs.length === 0 && <p className="p-6 text-center text-ace-muted">No learning runs yet.</p>}
      </div>
    </div>
  );
}

export default function RecordsPage({ readOnly = false }: { readOnly?: boolean } = {}) {
  const [tab, setTab] = useState<'activity' | 'readings' | 'learning'>('activity');
  const [period, setPeriod] = useState('');
  const label = useMemo(() => {
    if (!period) return 'All time';
    const [y, m, d] = period.split('-');
    return d ? new Date(Number(y), Number(m) - 1, Number(d)).toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' })
      : m ? `${MONTHS[Number(m) - 1]} ${y}` : y;
  }, [period]);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-6xl px-4 py-8">
        <div className="mb-1 flex items-center gap-3">
          <Database className="h-6 w-6 text-ace-terracotta" />
          <h1 className="text-2xl font-normal text-ace-ink">Records</h1>
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-800"><ShieldAlert className="h-3 w-3" /> {readOnly ? "Shared test data (view only)" : "Admin only"}</span>
        </div>
        <p className="mb-5 text-sm text-ace-muted">Every input and action, end to end. Viewing details and exports are logged too. Showing: <strong className="text-ace-ink">{label}</strong></p>
        <div className="grid gap-5 lg:grid-cols-[260px_1fr]">
          <div className="space-y-3">
            <Calendar period={period} onPeriod={setPeriod} />
            {period && <button onClick={() => setPeriod('')} className="w-full rounded-lg border border-ace-line bg-white/60 py-1.5 text-xs text-ace-muted hover:text-ace-ink">Show all time</button>}
          </div>
          <div className="min-w-0">
            <div className="mb-4 flex gap-1 border-b border-ace-line">
              {([['activity', 'Activity log', Database], ['readings', 'Readings', FlaskConical], ['learning', 'Self-learning', BrainCircuit]] as const).map(([id, l, Icon]) => (
                <button key={id} onClick={() => setTab(id)}
                        className={`-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm ${tab === id ? 'border-ace-terracotta text-ace-ink' : 'border-transparent text-ace-muted hover:text-ace-ink'}`}>
                  <Icon className="h-4 w-4" /> {l}
                </button>
              ))}
            </div>
            {tab === 'activity' && <ActivityTab period={period} />}
            {tab === 'readings' && <ReadingsTab period={period} readOnly={readOnly} />}
            {tab === 'learning' && <LearningTab />}
          </div>
        </div>
      </div>
    </div>
  );
}
