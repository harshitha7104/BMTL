// Sign-in for the web app. The session lives in an HttpOnly, SameSite=Strict cookie set by the
// server: JavaScript never sees or stores the token, so an injected script cannot steal it.
import { API_BASE_URL } from './apiBase';

export interface CurrentUser {
  username: string;
  role: 'user' | 'reviewer' | 'admin';
  auth_mode?: string;
  records_visible?: boolean;   // open testing: everyone may view Records (read-only)
}

export const SIGNED_OUT_EVENT = 'bmtl:signed-out';

async function errorText(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return typeof body.detail === 'string' ? body.detail : body.message ?? `${res.status}`;
  } catch {
    return `${res.status} ${res.statusText}`;
  }
}

export async function fetchCurrentUser(): Promise<CurrentUser | null> {
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/me`, { credentials: 'same-origin' });
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(await errorText(res));
  return res.json();
}

export async function signIn(username: string, password: string): Promise<CurrentUser> {
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/login`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new Error(await errorText(res));
  return res.json();
}

export async function signOut(): Promise<void> {
  await fetch(`${API_BASE_URL}/api/v1/auth/logout`, { method: 'POST', credentials: 'same-origin' });
}

/** Any API call that comes back 401 (session expired or revoked) sends the user back to the sign-in screen. */
export function installSignedOutWatcher(): void {
  const original = window.fetch.bind(window);
  window.fetch = async (...args: Parameters<typeof fetch>) => {
    const res = await original(...args);
    const url = typeof args[0] === 'string' ? args[0] : args[0] instanceof URL ? args[0].href : args[0].url;
    if (res.status === 401 && url.includes('/api/v1/') && !url.includes('/auth/')) {
      window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
    }
    return res;
  };
}
