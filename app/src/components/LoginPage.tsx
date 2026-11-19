import React, { useState } from 'react';
import BrandMark from './chat/BrandMark';
import { CurrentUser, signIn } from '../services/authService';

export default function LoginPage({ onSignedIn }: { onSignedIn: (user: CurrentUser) => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await signIn(username.trim(), password));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed');
      setPassword('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-ace-cream px-4">
      <form onSubmit={submit} className="w-full max-w-sm bg-white rounded-2xl shadow-sm border border-ace-stone p-6 space-y-4">
        <div className="flex items-center gap-2.5">
          <BrandMark />
          <div>
            <h1 className="text-lg font-semibold text-ace-ink">ScrapTrust · BMTL</h1>
            <p className="text-xs text-ace-muted">Sign in with the account your administrator gave you.</p>
          </div>
        </div>
        <label className="block text-sm">
          <span className="text-ace-ink">Username</span>
          <input value={username} onChange={e => setUsername(e.target.value)} autoComplete="username" required maxLength={64}
            className="mt-1 w-full rounded-lg border border-ace-stone px-3 py-2 focus:outline-none focus:ring-2 focus:ring-ace-terracotta/40" />
        </label>
        <label className="block text-sm">
          <span className="text-ace-ink">Password</span>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" required maxLength={256}
            className="mt-1 w-full rounded-lg border border-ace-stone px-3 py-2 focus:outline-none focus:ring-2 focus:ring-ace-terracotta/40" />
        </label>
        {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
        <button type="submit" disabled={busy || !username || !password}
          className="w-full rounded-lg bg-ace-terracotta text-white py-2 text-sm font-medium disabled:opacity-50">
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
