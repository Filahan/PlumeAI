'use client';

import { useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { Settings } from '@/lib/types';
import { TOOL_DESCRIPTORS, type ToolDescriptor } from '@/lib/tools/registry-client';
import { settings as settingsApi } from '@/lib/api';

const { clearToolCredentials, disconnectTool, saveToolCredentials } = settingsApi;
import {
  Plug,
  Check,
  ChevronRight,
  Copy,
  CheckCheck,
  ExternalLink,
  Eye,
  EyeOff,
  Loader2,
  AlertCircle,
  UserPlus,
} from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

function isToolConnected(tool: ToolDescriptor, settings: Settings): boolean {
  if (tool.connectMode === 'config') {
    return !!(tool.credentialsNamespace && settings.toolCredentials?.[tool.credentialsNamespace]);
  }
  return !!settings.tools?.[tool.name]?.connected;
}

export default function ToolsView({
  settings,
  setSettings,
}: {
  settings: Settings;
  setSettings: (s: Settings) => void;
}) {
  const params = useSearchParams();
  const errorMessage =
    params.get('status') === 'error' ? params.get('message') : null;

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

      {errorMessage && (
        <div className="mb-4 rounded-xl border border-[#D4183D]/30 bg-[#D4183D]/5 px-3.5 py-2.5 flex items-start gap-2 text-[12px] text-[#D4183D]">
          <AlertCircle size={14} strokeWidth={2.25} className="shrink-0 mt-0.5" />
          <span>
            <strong>Connection error:</strong> {errorMessage}. Reopen the tool to review setup.
          </span>
        </div>
      )}

      <div className="space-y-2">
        {TOOL_DESCRIPTORS.map((t) => (
          <ToolCard key={t.name} tool={t} settings={settings} setSettings={setSettings} />
        ))}
      </div>
    </div>
  );
}

/* ─────────────────────────── Card ─────────────────────────── */

function ToolCard({
  tool,
  settings,
  setSettings,
}: {
  tool: ToolDescriptor;
  settings: Settings;
  setSettings: (s: Settings) => void;
}) {
  const [open, setOpen] = useState(false);
  const connected = isToolConnected(tool, settings);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={`Open ${tool.label} settings`}
        className="w-full flex items-center gap-3 px-4 py-3 rounded-2xl border border-[color:var(--border)] bg-white hover:bg-[color:var(--surface-muted)]/60 transition text-left"
      >
        <div className="w-10 h-10 rounded-xl bg-white border border-[color:var(--border)] flex items-center justify-center shrink-0 overflow-hidden">
          {tool.logoUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={tool.logoUrl} alt={`${tool.label} logo`} className="w-5 h-5 object-contain" />
          ) : (
            <Plug size={18} strokeWidth={1.75} className="text-[color:var(--muted-foreground)]" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[14px] font-medium truncate">{tool.label}</div>
          <div className="text-[12px] text-[color:var(--muted-foreground)] truncate">{tool.description}</div>
          <div className="text-[11px] text-[color:var(--muted-foreground)] mt-0.5 font-mono">
            @{tool.name}
          </div>
        </div>
        {connected ? (
          <span className="inline-flex items-center gap-1 text-[12px] text-[#10A37F] font-medium">
            <Check size={13} strokeWidth={2.5} /> Connected
          </span>
        ) : (
          <span className="inline-flex items-center h-9 px-4 rounded-xl bg-[color:var(--primary)] text-white text-[13px] font-medium">
            Connect
          </span>
        )}
        <ChevronRight size={14} strokeWidth={1.75} className="text-[color:var(--muted-foreground)] shrink-0" />
      </button>

      <ToolModal
        tool={tool}
        settings={settings}
        setSettings={setSettings}
        close={() => setOpen(false)}
      />
    </Dialog>
  );
}

/* ─────────────────────────── Modal ─────────────────────────── */

function ToolModal({
  tool,
  settings,
  setSettings,
  close,
}: {
  tool: ToolDescriptor;
  settings: Settings;
  setSettings: (s: Settings) => void;
  close: () => void;
}) {
  const connected = isToolConnected(tool, settings);
  const hasCredentials =
    !!tool.credentialsNamespace && (tool.credentialsFields?.length ?? 0) > 0;
  const credsSaved = hasCredentials
    ? !!settings.toolCredentials?.[tool.credentialsNamespace!]
    : true;

  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries((tool.credentialsFields ?? []).map((f) => [f.name, ''])),
  );
  const [reveal, setReveal] = useState<Record<string, boolean>>({});
  const [showCredsEdit, setShowCredsEdit] = useState(!credsSaved);
  const [showSetup, setShowSetup] = useState(!credsSaved);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const credsDirty = Object.values(values).some((v) => v.trim().length > 0);
  const credsValid =
    (tool.credentialsFields ?? []).every((f) => values[f.name]?.trim().length > 0);

  const [origin, setOrigin] = useState('');
  useEffect(() => {
    setOrigin(window.location.origin);
  }, []);
  const interpolate = (v: string) => v.replaceAll('__ORIGIN__', origin || '');

  /* ─── Primary action ─── */

  async function onPrimary() {
    setError(null);
    setBusy(true);
    try {
      if (connected) {
        // ── Disconnect ──
        if (tool.connectMode === 'config' && tool.credentialsNamespace) {
          await clearToolCredentials(tool.credentialsNamespace);
          setSettings({
            ...settings,
            toolCredentials: {
              ...settings.toolCredentials,
              [tool.credentialsNamespace]: false,
            },
          });
        } else {
          await disconnectTool(tool.name);
          setSettings({
            ...settings,
            tools: { ...settings.tools, [tool.name]: { connected: false } },
          });
        }
        setBusy(false);
        close();
        return;
      }

      // ── Save dirty credentials first ──
      if (credsDirty && tool.credentialsNamespace) {
        await saveToolCredentials(tool.credentialsNamespace, values);
        setSettings({
          ...settings,
          toolCredentials: {
            ...settings.toolCredentials,
            [tool.credentialsNamespace]: true,
          },
        });
        setValues(Object.fromEntries((tool.credentialsFields ?? []).map((f) => [f.name, ''])));
      }

      // ── Connect ──
      if (tool.connectMode === 'config') {
        // Token-only: saving credentials is enough; the card flips to Connected via state.
        setBusy(false);
        close();
      } else {
        // OAuth: navigate to start. The browser leaves the page.
        window.location.href = tool.setupUrl;
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.');
      setBusy(false);
    }
  }

  /* ─── CTA label + disabled state ─── */

  const ctaLabel = connected
    ? 'Disconnect'
    : credsDirty
      ? 'Save & Connect'
      : credsSaved
        ? 'Connect'
        : 'Save & Connect';

  const ctaDisabled =
    busy ||
    (!connected && hasCredentials && !credsSaved && !credsValid) ||
    (!connected && hasCredentials && credsDirty && !credsValid);

  /* ─── Render ─── */

  return (
    <DialogContent className="sm:max-w-[560px]">
      <DialogHeader>
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-white border border-[color:var(--border)] flex items-center justify-center shrink-0 overflow-hidden">
            {tool.logoUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={tool.logoUrl} alt="" className="w-5 h-5 object-contain" />
            ) : (
              <Plug size={18} strokeWidth={1.75} className="text-[color:var(--muted-foreground)]" />
            )}
          </div>
          <div className="min-w-0">
            <DialogTitle>{tool.label}</DialogTitle>
            <div className="text-[11px] text-[color:var(--muted-foreground)] font-mono mt-0.5">
              @{tool.name}
            </div>
          </div>
        </div>
      </DialogHeader>

      <div className="overflow-y-auto max-h-[65vh] space-y-4 pr-1">
        <p className="text-[13px] text-[color:var(--foreground)] leading-relaxed">
          {tool.setup.intro}
        </p>

        {tool.name === 'discord' && credsSaved && (
          <DiscordInviteBlock />
        )}

        {/* ─── Credentials section ─── */}
        {hasCredentials && (
          <section className="rounded-xl border border-[color:var(--border)] bg-[color:var(--surface-muted)]/40 p-3">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-[11px] font-semibold uppercase tracking-wide text-[color:var(--muted-foreground)] flex items-center gap-1.5">
                Credentials
                {credsSaved && !showCredsEdit && (
                  <span className="inline-flex items-center gap-1 text-[#10A37F] font-medium normal-case tracking-normal">
                    <Check size={12} strokeWidth={2.5} /> Saved
                  </span>
                )}
              </h3>
              {credsSaved && (
                <button
                  type="button"
                  onClick={() => setShowCredsEdit((v) => !v)}
                  className="text-[11px] font-medium text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)] transition"
                >
                  {showCredsEdit ? 'Cancel' : 'Edit'}
                </button>
              )}
            </div>

            {(showCredsEdit || !credsSaved) && (
              <div className="space-y-2">
                {(tool.credentialsFields ?? []).map((f) => {
                  const shown = !f.secret || !!reveal[f.name];
                  return (
                    <div key={f.name}>
                      <label
                        htmlFor={`cred-${tool.name}-${f.name}`}
                        className="block text-[11px] font-medium text-[color:var(--foreground)] mb-1"
                      >
                        {f.label}
                      </label>
                      <div className="relative">
                        <input
                          id={`cred-${tool.name}-${f.name}`}
                          type={shown ? 'text' : 'password'}
                          value={values[f.name] ?? ''}
                          onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
                          placeholder={f.placeholder}
                          autoComplete="off"
                          spellCheck={false}
                          className="w-full h-9 rounded-lg border border-[color:var(--border)] bg-white pl-2.5 pr-9 text-[12px] outline-none placeholder:text-[#A8A8B0] focus:border-[#111111] focus:ring-2 focus:ring-black/5 transition"
                        />
                        {f.secret && (
                          <button
                            type="button"
                            onClick={() => setReveal({ ...reveal, [f.name]: !reveal[f.name] })}
                            tabIndex={-1}
                            aria-label={shown ? 'Hide' : 'Show'}
                            className="absolute right-2 top-1/2 -translate-y-1/2 text-[color:var(--muted-foreground)] hover:text-[#111111] transition-colors"
                          >
                            {shown ? <EyeOff size={14} /> : <Eye size={14} />}
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        )}

        {/* ─── Setup guide (collapsible) ─── */}
        <details
          open={showSetup}
          onToggle={(e) => setShowSetup((e.target as HTMLDetailsElement).open)}
          className="rounded-xl border border-[color:var(--border)] bg-white"
        >
          <summary className="px-3 py-2.5 text-[12px] font-medium text-[color:var(--foreground)] cursor-pointer list-none flex items-center justify-between hover:bg-[color:var(--surface-muted)]/40 transition">
            <span>How to obtain these credentials</span>
            <ChevronRight
              size={14}
              strokeWidth={2}
              className={`text-[color:var(--muted-foreground)] transition-transform ${showSetup ? 'rotate-90' : ''}`}
            />
          </summary>
          <div className="px-3 pb-3 pt-1">
            <ol className="space-y-3">
              {tool.setup.steps.map((step, i) => (
                <li key={i} className="flex gap-3">
                  <span className="shrink-0 w-5 h-5 rounded-full bg-[color:var(--surface-muted)] text-[color:var(--foreground)] text-[11px] font-semibold inline-flex items-center justify-center mt-0.5">
                    {i + 1}
                  </span>
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <div className="text-[12px] font-medium text-[color:var(--foreground)] leading-snug">
                      {step.title}
                    </div>
                    {step.description && (
                      <div className="text-[11px] text-[color:var(--muted-foreground)] leading-relaxed">
                        {step.description}
                      </div>
                    )}
                    {step.link && (
                      <a
                        href={step.link.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-[11px] underline underline-offset-2 hover:text-[color:var(--foreground)]"
                      >
                        {step.link.label} <ExternalLink size={10} strokeWidth={2} />
                      </a>
                    )}
                    {step.copy && (
                      <CopyableValue label={step.copy.label} value={interpolate(step.copy.value)} />
                    )}
                    {step.code && <CopyableCode value={interpolate(step.code)} />}
                  </div>
                </li>
              ))}
            </ol>
            {tool.setup.note && (
              <p className="mt-3 pt-3 border-t border-[color:var(--border)] text-[11px] text-[color:var(--muted-foreground)] leading-relaxed">
                {tool.setup.note}
              </p>
            )}
          </div>
        </details>

        {error && (
          <div className="rounded-lg border border-[#D4183D]/30 bg-[#D4183D]/5 px-3 py-2 text-[12px] text-[#D4183D] flex items-start gap-2">
            <AlertCircle size={13} strokeWidth={2.25} className="shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}
      </div>

      {/* ─── Bottom CTA ─── */}
      <div className="flex justify-end pt-3 mt-1 border-t border-[color:var(--border)] -mx-4 px-4">
        <button
          type="button"
          onClick={onPrimary}
          disabled={ctaDisabled}
          className={`h-9 px-4 inline-flex items-center gap-1.5 rounded-xl text-[13px] font-medium transition ${
            connected
              ? 'bg-white border border-[#D4183D]/30 text-[#D4183D] hover:bg-[#D4183D]/5'
              : 'bg-[color:var(--primary)] text-white hover:opacity-90'
          } disabled:opacity-40 disabled:cursor-not-allowed`}
        >
          {busy ? (
            <>
              <Loader2 size={14} className="animate-spin" />
              {connected ? 'Disconnecting…' : 'Connecting…'}
            </>
          ) : (
            ctaLabel
          )}
        </button>
      </div>
    </DialogContent>
  );
}

/* ─────────────────────────── Copyable helpers ─────────────────────────── */

function CopyableValue({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked */
    }
  };
  return (
    <div>
      <div className="text-[10px] text-[color:var(--muted-foreground)] mb-1">{label}</div>
      <div className="flex items-center gap-1.5">
        <code className="flex-1 min-w-0 truncate text-[11px] bg-[color:var(--surface-muted)] border border-[color:var(--border)] rounded-md px-2 py-1.5 font-mono">
          {value}
        </code>
        <button
          type="button"
          onClick={copy}
          aria-label={`Copy ${label}`}
          className="h-7 w-7 inline-flex items-center justify-center rounded-md bg-white border border-[color:var(--border)] text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)] hover:text-[color:var(--foreground)] transition shrink-0"
        >
          {copied ? <CheckCheck size={12} strokeWidth={2} /> : <Copy size={12} strokeWidth={2} />}
        </button>
      </div>
    </div>
  );
}

/* ─────────────────────────── Discord invite block ─────────────────────────── */

function DiscordInviteBlock() {
  const [meta, setMeta] = useState<{
    bot_name: string | null;
    application_id: string | null;
    invite_url: string | null;
  } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    settingsApi
      .discordMeta()
      .then((m) => {
        if (!cancelled) setMeta(m);
      })
      .catch(() => {
        if (!cancelled) setMeta({ bot_name: null, application_id: null, invite_url: null });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="rounded-xl border border-[color:var(--border)] bg-white p-3 flex items-center gap-2 text-[12px] text-[color:var(--muted-foreground)]">
        <Loader2 size={13} className="animate-spin" />
        Checking bot…
      </div>
    );
  }

  if (!meta?.invite_url) {
    return (
      <div className="rounded-xl border border-[#D4183D]/30 bg-[#D4183D]/5 p-3 flex items-start gap-2 text-[12px] text-[#D4183D]">
        <AlertCircle size={13} strokeWidth={2.25} className="shrink-0 mt-0.5" />
        <span>
          Couldn&apos;t reach Discord — check your bot token above.
        </span>
      </div>
    );
  }

  const botName = meta.bot_name || 'Your bot';

  return (
    <div className="rounded-xl border border-[#5865F2]/30 bg-[#5865F2]/5 p-3 space-y-3">
      <div>
        <div className="text-[13px] font-medium text-[color:var(--foreground)] flex items-center gap-1.5">
          <Check size={13} strokeWidth={2.5} className="text-[#10A37F]" />
          {botName} is ready
        </div>
        <p className="text-[11px] text-[color:var(--muted-foreground)] mt-1 leading-relaxed">
          Add the bot to a Discord server so it can list channels and post messages.
        </p>
      </div>
      <a
        href={meta.invite_url}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center justify-center gap-1.5 h-9 px-4 w-full rounded-xl bg-[#5865F2] text-white text-[13px] font-medium hover:bg-[#4752C4] transition"
        title="Required scopes: View Channels, Send Messages, Read Message History"
      >
        <UserPlus size={14} strokeWidth={2} />
        Invite to a Discord server
      </a>
    </div>
  );
}

function CopyableCode({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked */
    }
  };
  return (
    <div className="relative">
      <pre className="text-[11px] bg-[color:var(--surface-muted)] border border-[color:var(--border)] rounded-md px-2 py-2 pr-9 font-mono overflow-x-auto whitespace-pre">
{value}
      </pre>
      <button
        type="button"
        onClick={copy}
        aria-label="Copy snippet"
        className="absolute top-1.5 right-1.5 h-6 w-6 inline-flex items-center justify-center rounded bg-white border border-[color:var(--border)] text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)] hover:text-[color:var(--foreground)] transition"
      >
        {copied ? <CheckCheck size={11} strokeWidth={2} /> : <Copy size={11} strokeWidth={2} />}
      </button>
    </div>
  );
}
