'use client';

import * as React from 'react';
import { useState } from 'react';
import { AlertCircle, ArrowRight, Eye, EyeOff, Loader2 } from 'lucide-react';

export default function LoginPage() {
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  const handleSubmit = async (e: React.SyntheticEvent<HTMLFormElement>) => {
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

  const hasError = !!error;

  return (
    <div
      className="fixed inset-3 rounded-3xl bg-white border border-[color:var(--border)] overflow-hidden flex items-center justify-center"
      suppressHydrationWarning
    >
      <div className="w-full max-w-[400px] px-6">
        <div
          className="flex flex-col items-center"
          style={{ animation: 'fade-in-up-1 400ms ease-out 80ms both' }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo.png" alt="" className="h-16 w-auto" />
          <span className="mt-3 text-[17px] font-semibold tracking-[-0.015em] text-[#111111]">
            PlumeAI
          </span>
          <p className="mt-1.5 text-[13px] text-[color:var(--muted-foreground)]">
            Private AI for chat &amp; automations
          </p>
        </div>

        <h1
          className="text-center mt-12 text-[26px] font-semibold tracking-[-0.025em] text-[#111111]"
          style={{ animation: 'fade-in-up-2 350ms ease-out 160ms both' }}
        >
          Sign in to continue
        </h1>

        <form
          onSubmit={handleSubmit}
          className="mt-8"
          style={{ animation: 'fade-in-up-3 350ms ease-out 240ms both' }}
        >
          <label htmlFor="password" className="sr-only">
            Password
          </label>

          <div className="relative">
            <input
              id="password"
              type={showPassword ? 'text' : 'password'}
              autoFocus
              autoComplete="current-password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-invalid={hasError}
              aria-describedby={hasError ? 'login-error' : undefined}
              className={`w-full h-11 rounded-2xl border bg-white pl-3.5 pr-10 text-[14px] outline-none placeholder:text-[#A8A8B0] transition-[border-color,box-shadow] duration-150 [color-scheme:light] ${
                hasError
                  ? 'border-[#D4183D] focus:ring-4 focus:ring-[#D4183D]/15'
                  : 'border-[#ECECEF] focus:border-[#111111] focus:ring-4 focus:ring-black/5'
              }`}
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              tabIndex={-1}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-[color:var(--muted-foreground)] hover:text-[#111111] transition-colors"
            >
              {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>

          <div className="min-h-5 mt-2 flex items-center gap-1.5 text-[13px] text-[#D4183D]">
            {hasError && (
              <span
                id="login-error"
                role="alert"
                className="inline-flex items-center gap-1.5"
                style={{ animation: 'fade-in-up-2 200ms ease-out both' }}
              >
                <AlertCircle size={14} strokeWidth={2.25} />
                {error}
              </span>
            )}
          </div>

          <button
            type="submit"
            disabled={loading || !password}
            className={`mt-4 w-full inline-flex items-center justify-center gap-1.5 h-11 rounded-2xl bg-[#111111] text-white text-[14px] font-medium transition-all focus-visible:ring-4 focus-visible:ring-black/10 [&_svg]:transition-transform [&_svg]:duration-150 ${
              loading
                ? 'pointer-events-none'
                : !password
                  ? 'opacity-50 pointer-events-none cursor-not-allowed'
                  : 'hover:bg-[#1F1F23] active:scale-[0.98] hover:[&_svg]:translate-x-0.5'
            }`}
          >
            {loading ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                Signing in…
              </>
            ) : (
              <>
                Continue
                <ArrowRight size={16} strokeWidth={2.25} />
              </>
            )}
          </button>
        </form>
      </div>

      <p
        className="absolute bottom-8 left-1/2 -translate-x-1/2 text-[12px] text-[color:var(--muted-foreground)]"
        style={{ animation: 'fade-in-up-3 350ms ease-out 400ms both' }}
      >
        Self-hosted · v0.1
      </p>
    </div>
  );
}
