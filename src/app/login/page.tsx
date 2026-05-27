'use client';

import { useState, FormEvent } from 'react';
import { ArrowRight } from 'lucide-react';

export default function LoginPage() {
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!password) return;
    setError(null);
    setLoading(true);
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ password }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.error || 'Login failed');
        return;
      }
      // Cookie is now set; reload so middleware reads ?next= and routes us to the right place.
      window.location.reload();
    } catch {
      setError('Network error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 flex items-center justify-center px-6">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-3xl border border-[color:var(--border)] bg-white p-8 space-y-5"
      >
        <div className="text-center space-y-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo.png" alt="" className="h-8 w-auto mx-auto" />
          <div className="text-[20px] font-semibold tracking-tight">Welcome to PlumeAI</div>
          <p className="text-[13px] text-[color:var(--muted-foreground)]">Enter your admin password to continue.</p>
        </div>

        <input
          type="password"
          autoFocus
          autoComplete="current-password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full h-10 px-0 bg-transparent border-0 border-b border-[color:var(--border)] text-[14px] outline-none focus:border-[color:var(--foreground)] transition placeholder:text-[color:var(--muted-foreground)]"
        />

        {error && (
          <p className="text-[12px] text-red-600 text-center">{error}</p>
        )}

        <button
          type="submit"
          disabled={loading || !password}
          className="w-full inline-flex items-center justify-center gap-1.5 h-11 rounded-full bg-[color:var(--primary)] text-white text-[13px] font-medium hover:opacity-90 transition disabled:opacity-30 disabled:cursor-not-allowed"
        >
          {loading ? 'Signing in…' : 'Sign in'}
          {!loading && <ArrowRight size={14} strokeWidth={2.5} />}
        </button>
      </form>
    </div>
  );
}
