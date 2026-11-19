// ============================================================
// Library (every user, own items only) and admin Records API client
// ============================================================

import { API_BASE_URL } from './apiBase';

export type LibraryKind = 'image' | 'spectrum' | 'audio' | 'video' | 'document' | 'xrf' | 'report' | 'assessment';

export interface LibraryItem {
  item_id: string;
  session_id: string | null;
  attachment_id: string | null;
  kind: LibraryKind;
  filename: string | null;
  title: string;
  pinned: boolean;
  created_at: number;   // epoch seconds
  updated_at: number;
  size_bytes: number;
  preview?: string;
  text?: string;
}

export interface ActivityEvent {
  id: number;
  ts: number;
  day: string;
  username: string | null;
  action: string;
  session_id: string | null;
  object_id: string | null;
  summary: string;
  detail?: unknown;
}

export interface Observation {
  id: number;
  ts: number;
  day: string;
  username: string | null;
  label: string;
  instrument: string;
  basis: string;
  kind: string;
  observed: Record<string, number>;
  results: { values?: Record<string, number>; bands?: Record<string, number> } | null;
  material: string | null;
  compound: string | null;
  label_state: 'UNLABELLED' | 'CONFIRMED';
  icp: Record<string, number> | null;
  icp_by: string | null;
  icp_note: string | null;
}

export interface LearningRun {
  id: number;
  ts: number;
  status: string;
  confirmed_rows: number;
  promoted: boolean;
  note: string;
  metrics: Record<string, unknown> | null;
}

async function readError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body);
  } catch {
    return `${res.status} ${res.statusText}`;
  }
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, { credentials: 'same-origin' });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

async function sendJson<T>(path: string, method: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method, credentials: 'same-origin',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

const qs = (params: Record<string, string | number | undefined | null>) => {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') p.set(k, String(v)); });
  const s = p.toString();
  return s ? `?${s}` : '';
};

// ---------------------------------------------------------------- library
export const listLibrary = (q = '', kind?: LibraryKind | null, offset = 0) =>
  getJson<{ total: number; items: LibraryItem[] }>(`/api/v1/library${qs({ q, kind, offset, limit: 60 })}`);
export const openLibraryItem = (id: string) => getJson<LibraryItem>(`/api/v1/library/${encodeURIComponent(id)}`);
export const updateLibraryItem = (id: string, patch: { title?: string; pinned?: boolean }) =>
  sendJson<LibraryItem>(`/api/v1/library/${encodeURIComponent(id)}`, 'PATCH', patch);
export const removeLibraryItem = (id: string) => sendJson<{ removed: string }>(`/api/v1/library/${encodeURIComponent(id)}`, 'DELETE');
export const libraryDownloadUrl = (id: string, format: 'txt' | 'pdf' | 'original') =>
  `${API_BASE_URL}/api/v1/library/${encodeURIComponent(id)}/download?format=${format}`;

// ---------------------------------------------------------------- admin records
export interface CalendarCounts { level: 'years' | 'months' | 'days'; year?: number; month?: number; counts: Record<string, number> }
export const recordsCalendar = (year?: number, month?: number) =>
  getJson<CalendarCounts>(`/api/v1/admin/records/calendar${qs({ year, month })}`);
export const recordsActions = () => getJson<{ actions: string[] }>('/api/v1/admin/records/actions');
export const recordsActivity = (p: { period?: string; q?: string; username?: string; action?: string; offset?: number }) =>
  getJson<{ total: number; items: ActivityEvent[] }>(`/api/v1/admin/records/activity${qs({ ...p, limit: 100 })}`);
export const recordsEvent = (id: number) => getJson<ActivityEvent>(`/api/v1/admin/records/activity/${id}`);
export const recordsExportUrl = (period: string | undefined, format: 'jsonl' | 'csv') =>
  `${API_BASE_URL}/api/v1/admin/records/export${qs({ period, format })}`;
export const recordsObservations = (p: { period?: string; state?: string; offset?: number }) =>
  getJson<{ total: number; items: Observation[]; counts: Record<string, number> }>(`/api/v1/admin/records/observations${qs({ ...p, limit: 100 })}`);
export const setObservationIcp = (id: number, values: Record<string, number>, note: string) =>
  sendJson<Observation>(`/api/v1/admin/records/observations/${id}/icp`, 'POST', { values, note });
export const clearObservationIcp = (id: number) => sendJson<unknown>(`/api/v1/admin/records/observations/${id}/icp`, 'DELETE');
export const learningStatus = () => getJson<{ runs: LearningRun[]; observations: Record<string, number> }>('/api/v1/admin/records/learning');
