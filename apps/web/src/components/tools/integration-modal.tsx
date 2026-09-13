'use client';

import { useState, useSyncExternalStore } from 'react';
import { AlertCircle, Loader2, Plug } from 'lucide-react';
import type { Settings } from '@/lib/types';
import type { CatalogIntegration } from '@/lib/automations/types';
import { settings as settingsApi } from '@/lib/api';
import { DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import CredentialsFields from '@/components/tools/credentials-fields';
import DiscordInviteBlock from '@/components/tools/discord-invite-block';
import SetupGuide from '@/components/tools/setup-guide';
import { isToolConnected } from '@/components/tools/connection';

const { clearToolCredentials, disconnectTool, saveToolCredentials } = settingsApi;

/** `window.location.origin`, read the one way that survives hydration: the server render
 *  has no origin, the client one does, and `useSyncExternalStore` reconciles the two
 *  without a setState-in-effect. The value never changes, so nothing ever notifies. */
const subscribeToNothing = () => () => {};
const readOrigin = () => window.location.origin;
const noOrigin = () => '';

/** The per-integration setup sheet: credentials, the guide for obtaining them, and the
 *  one Connect/Disconnect action at the bottom. */
export default function IntegrationModal({
  tool,
  settings,
  setSettings,
  close,
}: {
  tool: CatalogIntegration;
  settings: Settings;
  setSettings: (s: Settings) => void;
  close: () => void;
}) {
  const connected = isToolConnected(tool, settings);
  const fields = tool.credentialsFields ?? [];
  const hasCredentials = !!tool.credentialsNamespace && fields.length > 0;
  const credsSaved = hasCredentials
    ? !!settings.toolCredentials?.[tool.credentialsNamespace!]
    : true;

  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((f) => [f.name, ''])),
  );
  const [showSetup, setShowSetup] = useState(!credsSaved);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const credsDirty = Object.values(values).some((v) => v.trim().length > 0);
  const credsValid = fields.every((f) => values[f.name]?.trim().length > 0);

  const origin = useSyncExternalStore(subscribeToNothing, readOrigin, noOrigin);
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
        setValues(Object.fromEntries(fields.map((f) => [f.name, ''])));
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
        {tool.setup?.intro && (
          <p className="text-[13px] text-[color:var(--foreground)] leading-relaxed">
            {tool.setup.intro}
          </p>
        )}

        {tool.name === 'discord' && credsSaved && <DiscordInviteBlock />}

        {hasCredentials && (
          <CredentialsFields
            toolName={tool.name}
            fields={fields}
            values={values}
            onChange={setValues}
            saved={credsSaved}
          />
        )}

        <SetupGuide
          setup={tool.setup}
          open={showSetup}
          onOpenChange={setShowSetup}
          interpolate={interpolate}
        />

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
