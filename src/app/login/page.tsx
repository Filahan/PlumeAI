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
      // Honour ?next= but never bounce back to /login.
      const params = new URLSearchParams(window.location.search);
      const raw = params.get('next') || '/';
      const dest = raw.startsWith('/') && !raw.startsWith('/login') ? raw : '/';
      // Hard navigate so the cookie just set by the POST is sent on the next request
      // (no client-router race with middleware).
      window.location.replace(dest);
    } catch {
      setError('Network error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-6 bg-white">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-2xl border border-black/[0.08] bg-white p-6 space-y-4"
      >
        <div className="text-center space-y-1.5">
          <div className="text-[20px] font-semibold tracking-tight">
            PlumeAI
          </div>
          <p className="text-[13px] text-[#8e8e8e]">Enter your admin password to continue.</p>
        </div>

        <input
          type="password"
          autoFocus
          autoComplete="current-password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full h-10 rounded-xl border border-black/[0.08] bg-[#FAFAFA] px-3 text-[13px] outline-none focus:bg-white focus:border-black/[0.15] transition"
        />

        {error && (
          <p className="text-[12px] text-red-600 text-center">{error}</p>
        )}

        <button
          type="submit"
          disabled={loading || !password}
          className="w-full inline-flex items-center justify-center gap-1.5 h-10 rounded-xl bg-[#1c1c1c] text-white text-[13px] font-medium hover:bg-[#333] transition disabled:opacity-30 disabled:cursor-not-allowed"
        >
          {loading ? 'Signing in…' : 'Sign in'}
          {!loading && <ArrowRight size={14} strokeWidth={2.5} />}
        </button>
      </form>
    </div>
  );
}
