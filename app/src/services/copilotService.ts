// ============================================================
// Copilot API client — chat with the scrap / waste / mineral assistant
// ============================================================

import { API_BASE_URL } from './apiBase';

// LLM turns that call several tools can take a while.
const CHAT_TIMEOUT_MS = 180000;

export interface CopilotProviderInfo {
  name: string;
  display_name: string;
  model: string;
  configured: boolean;
  supports_vision: boolean;
}

export interface CopilotToolCall {
  name: string;
  input: Record<string, unknown>;
  output: unknown;
  is_error: boolean;
  duration_ms: number;
}

export type AttachmentKind = 'image' | 'spectrum' | 'audio' | 'video' | 'document' | 'xrf' | 'report';

/** Answer-checker agent result: were the composition numbers in the answer traceable to data? */
export interface CopilotVerification {
  status: 'verified' | 'unverified_numbers' | 'no_evidence';
  numbers_checked: number;
  ungrounded: { value: string; context: string }[];
  repaired?: boolean;
}

/** A file an agent produced for download (e.g. the report-writer's Word report). */
export interface CopilotGeneratedFile {
  attachment_id: string;
  filename: string;
  size_bytes: number;
  kind: 'report';
}

export interface CopilotAttachment {
  attachment_id: string;
  kind: AttachmentKind;
  filename: string;
  content_type: string;
  size_bytes: number;
  text?: string | null;     // transcript (audio/video) or extracted text (document)
  source?: string | null;   // "video_1" for frames taken from a video
  note?: string | null;
}

export interface CopilotSessionSummary {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  turns: number;
}

export interface CopilotStoredTurn {
  role: 'user' | 'assistant';
  text: string;
  attachment_ids: string[];
  provider?: string;
  model?: string;
  tool_calls?: CopilotToolCall[];
  feedback?: { rating: 'up' | 'down'; corrected_category?: string | null } | null;
  verification?: CopilotVerification;
  generated?: string[];
  created_at?: string;
}

export interface CopilotSession {
  session_id: string;
  title: string;
  turns: CopilotStoredTurn[];
  attachments: Record<string, CopilotAttachment>;
}

export interface CopilotChatResponse {
  session_id: string;
  reply: string;
  provider: string;
  model: string;
  tool_calls: CopilotToolCall[];
  attachments: CopilotAttachment[];
  stop_reason: string | null;
  usage: Record<string, number>;
  verification?: CopilotVerification;
  speech?: string;            // short spoken summary for voice mode
  generated_files?: CopilotGeneratedFile[];
}

async function readError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body);
  } catch {
    return `${res.status} ${res.statusText}`;
  }
}

export interface CopilotFeedbackResult {
  saved: boolean;
  turn_index: number;
  labels_recorded: number;
  predicted_category: string | null;
}

export async function sendCopilotFeedback(
  sessionId: string,
  body: { turn_index: number; rating: 'up' | 'down'; corrected_category?: string | null; note?: string | null },
): Promise<CopilotFeedbackResult> {
  const res = await fetch(`${API_BASE_URL}/api/v1/copilot/sessions/${encodeURIComponent(sessionId)}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function listCopilotProviders(): Promise<{
  default: string;
  providers: CopilotProviderInfo[];
  waste_categories: string[];
}> {
  const res = await fetch(`${API_BASE_URL}/api/v1/copilot/providers`);
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

/** Turn any failure into one sentence a non-technical user can act on. */
export function friendlyError(err: unknown): string {
  const msg = err instanceof Error ? err.message : String(err);
  if (/failed to fetch|networkerror|load failed|network request failed/i.test(msg))
    return "I couldn't reach the ScrapTrust server. Check your internet connection, then press Try again.";
  if (/took too long/i.test(msg)) return 'This is taking longer than usual. Press Try again, or send fewer or smaller files.';
  if (/too many|rate limit|429/i.test(msg)) return "You're sending messages very quickly. Wait a minute, then press Try again.";
  if (/busy|503|try again shortly/i.test(msg)) return 'ScrapTrust is busy right now. Wait a few seconds, then press Try again.';
  if (/sign in|401|not authenticated/i.test(msg)) return 'Your session has ended. Please sign in again.';
  if (/too large|413|exceeds/i.test(msg)) return `That file is too big. ${msg}`;
  if (/quota|storage/i.test(msg)) return `You've run out of storage space. ${msg} Delete old conversations to free space.`;
  return `Something went wrong: ${msg}. Press Try again; if it keeps happening, contact your ScrapTrust administrator.`;
}

export async function sendCopilotMessage(params: {
  message: string;
  files: File[];
  sessionId?: string | null;
  provider?: string | null;
  signal?: AbortSignal;
}): Promise<CopilotChatResponse> {
  const form = new FormData();
  form.append('message', params.message);
  if (params.sessionId) form.append('session_id', params.sessionId);
  if (params.provider) form.append('provider', params.provider);
  params.files.forEach(f => form.append('files', f));

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), CHAT_TIMEOUT_MS);
  let stoppedByUser = false;
  params.signal?.addEventListener('abort', () => { stoppedByUser = true; controller.abort(); });
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/copilot/chat`, {
      method: 'POST',
      body: form,
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(await readError(res));
    return res.json();
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      if (stoppedByUser) throw new Error('STOPPED');
      throw new Error('The copilot took too long to answer.');
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export async function listCopilotSessions(): Promise<CopilotSessionSummary[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/copilot/sessions`);
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()).sessions;
}

export async function getCopilotSession(sessionId: string): Promise<CopilotSession> {
  const res = await fetch(`${API_BASE_URL}/api/v1/copilot/sessions/${encodeURIComponent(sessionId)}`);
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function deleteCopilotSession(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/api/v1/copilot/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(await readError(res));
}

export function copilotAttachmentUrl(sessionId: string, attachmentId: string): string {
  return `${API_BASE_URL}/api/v1/copilot/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}`;
}

/** Speech-to-text for a microphone recording (transcribed locally on the server with Whisper). */
export async function transcribeRecording(audio: Blob, filename = 'recording.webm'): Promise<{ text: string; language?: string; duration_s?: number }> {
  const form = new FormData();
  form.append('file', audio, filename);
  const res = await fetch(`${API_BASE_URL}/api/v1/copilot/transcribe`, { method: 'POST', body: form });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}
