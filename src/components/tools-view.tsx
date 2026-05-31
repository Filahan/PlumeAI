'use client';

import { useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { Settings } from '@/lib/types';
import { TOOL_DESCRIPTORS } from '@/lib/tools/registry-client';
import { disconnectTool } from '@/lib/actions/settings';
import { Plug, Check, AlertTriangle, Copy, CheckCheck, ExternalLink } from 'lucide-react';

export default function ToolsView({
  settings, setSettings,
}: {
  settings: Settings;
  setSettings: (s: Settings) => void;
}) {
  const params = useSearchParams();
  const showGmailSetup = params.get('gmail_setup') === 'required';

  return (
    <div className="w-full max-w-[760px] mx-auto px-8 py-8 overflow-y-auto h-full">
      <div className="mb-6">
        <h1 className="text-[20px] font-semibold tracking-tight flex items-center gap-2">
          <Plug size={18} strokeWidth={1.75} /> Tools
        </h1>
        <p className="text-[11px] text-[color:var(--muted-foreground)]">
          Connect external accounts so your automations can call them. Tokens are encrypted at rest.
        </p>
      </div>

      {showGmailSetup && <GmailSetupGuide />}

      <div className="space-y-2">
        {TOOL_DESCRIPTORS.map((t) => {
          const connected = !!settings.tools?.[t.name]?.connected;
          return (
            <div
              key={t.name}
              className="flex items-center gap-3 px-4 py-3 rounded-2xl border border-[color:var(--border)] bg-white"
            >
              <div className="w-10 h-10 rounded-xl bg-white border border-[color:var(--border)] flex items-center justify-center shrink-0 overflow-hidden">
                {t.logoUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={t.logoUrl} alt={`${t.label} logo`} className="w-5 h-5 object-contain" />
                ) : (
                  <Plug size={18} strokeWidth={1.75} className="text-[color:var(--muted-foreground)]" />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[14px] font-medium truncate">{t.label}</div>
                <div className="text-[12px] text-[color:var(--muted-foreground)] truncate">{t.description}</div>
                <div className="text-[11px] text-[color:var(--muted-foreground)] mt-0.5 font-mono">
                  @{t.name}
                </div>
              </div>
              {connected ? (
                <>
                  <span className="inline-flex items-center gap-1 text-[12px] text-[#10A37F] font-medium">
                    <Check size={13} strokeWidth={2.5} /> Connected
                  </span>
                  <button
                    type="button"
                    onClick={async () => {
                      await disconnectTool(t.name);
                      setSettings({
                        ...settings,
                        tools: { ...settings.tools, [t.name]: { connected: false } },
                      });
                    }}
                    className="h-9 px-3 rounded-xl text-[13px] font-medium text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)] hover:text-[color:var(--foreground)] transition"
                  >
                    Disconnect
                  </button>
                </>
              ) : (
                <a
                  href={t.setupUrl}
                  className="h-9 px-4 inline-flex items-center rounded-xl bg-[color:var(--primary)] text-white text-[13px] font-medium hover:opacity-90 transition"
                >
                  Connect
                </a>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ─────────────────────────── Gmail setup guide ─────────────────────────── */

function GmailSetupGuide() {
  const [redirectUri, setRedirectUri] = useState('');
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setRedirectUri(`${window.location.origin}/api/tools/gmail/oauth/callback`);
  }, []);

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard blocked — silently ignore; user can still select+copy by hand
    }
  };

  const envSnippet = `GOOGLE_OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com\nGOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-your-secret`;

  return (
    <div className="mb-4 rounded-2xl border border-amber-200 bg-amber-50/60 p-5">
      <div className="flex items-start gap-3 mb-3">
        <div className="w-9 h-9 rounded-xl bg-white border border-amber-200 flex items-center justify-center shrink-0">
          <AlertTriangle size={16} strokeWidth={2} className="text-amber-600" />
        </div>
        <div>
          <h2 className="text-[14px] font-semibold text-amber-900">Gmail setup required</h2>
          <p className="text-[12px] text-amber-900/80">
            The Gmail integration needs Google OAuth credentials on the server. Follow the steps below — it takes about 3 minutes.
          </p>
        </div>
      </div>

      <ol className="space-y-3 text-[12px] text-amber-950">
        <li className="flex gap-2.5">
          <span className="shrink-0 w-5 h-5 rounded-full bg-amber-200 text-amber-900 text-[11px] font-semibold inline-flex items-center justify-center">1</span>
          <span>
            Open the{' '}
            <a
              href="https://console.cloud.google.com/apis/credentials"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-0.5 underline underline-offset-2 hover:text-amber-700"
            >
              Google Cloud Console <ExternalLink size={11} strokeWidth={2} />
            </a>{' '}
            and create an OAuth client ID of type <strong>Web application</strong>.
          </span>
        </li>

        <li className="flex gap-2.5">
          <span className="shrink-0 w-5 h-5 rounded-full bg-amber-200 text-amber-900 text-[11px] font-semibold inline-flex items-center justify-center">2</span>
          <div className="min-w-0 flex-1">
            <div>Add this <strong>Authorized redirect URI</strong>:</div>
            <div className="mt-1.5 flex items-center gap-1.5">
              <code className="flex-1 min-w-0 truncate text-[11px] bg-white border border-amber-200 rounded-lg px-2.5 py-1.5 font-mono text-amber-900">
                {redirectUri || '—'}
              </code>
              <button
                type="button"
                onClick={() => redirectUri && copy(redirectUri)}
                aria-label="Copy redirect URI"
                className="h-8 w-8 inline-flex items-center justify-center rounded-lg bg-white border border-amber-200 text-amber-700 hover:bg-amber-100 transition shrink-0"
              >
                {copied ? <CheckCheck size={13} strokeWidth={2} /> : <Copy size={13} strokeWidth={2} />}
              </button>
            </div>
          </div>
        </li>

        <li className="flex gap-2.5">
          <span className="shrink-0 w-5 h-5 rounded-full bg-amber-200 text-amber-900 text-[11px] font-semibold inline-flex items-center justify-center">3</span>
          <div className="min-w-0 flex-1">
            <div>Copy the generated client ID and secret into your project&apos;s <code className="text-[11px] font-mono">.env</code>:</div>
            <pre className="mt-1.5 text-[11px] bg-white border border-amber-200 rounded-lg px-2.5 py-2 font-mono text-amber-900 overflow-x-auto whitespace-pre">
{envSnippet}
            </pre>
          </div>
        </li>

        <li className="flex gap-2.5">
          <span className="shrink-0 w-5 h-5 rounded-full bg-amber-200 text-amber-900 text-[11px] font-semibold inline-flex items-center justify-center">4</span>
          <span>
            Restart the app container (<code className="text-[11px] font-mono">docker compose restart app</code>), then click <strong>Connect</strong> on the Gmail card above.
          </span>
        </li>
      </ol>
    </div>
  );
}
