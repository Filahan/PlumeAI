'use client';

import SettingsContent from '@/components/settings-content';
import { ProviderLogo } from '@/components/provider-logo';
import { PROVIDER_ACCENT, Settings } from '@/lib/types';

interface ProviderOnboardingProps {
  settings: Settings;
  setSettings: (s: Settings) => void;
}

/** First-run card shown in place of the chat composer until at least one provider key exists.
 *  The inline SettingsContent auto-opens the "add provider" form, and saving the first key also
 *  sets the default model, so the chat view can swap straight to the composer afterwards. */
export default function ProviderOnboarding({ settings, setSettings }: ProviderOnboardingProps) {
  return (
    <div className="w-full max-w-[520px] rounded-3xl border border-[color:var(--border)] bg-white p-8">
      <div className="text-center mb-6">
        <div className="inline-flex items-center justify-center gap-2 mb-4">
          <ProviderLogo provider="openai" size={22} className={PROVIDER_ACCENT.openai} />
          <ProviderLogo provider="anthropic" size={22} className={PROVIDER_ACCENT.anthropic} />
        </div>
        <h1 className="text-[22px] font-semibold mb-1 tracking-tight">Connect a provider</h1>
        <p className="text-[13px] text-[color:var(--muted-foreground)]">
          PlumeAI needs an API key to chat. Add one from OpenAI or Anthropic —
          it stays on your server, encrypted at rest.
        </p>
      </div>

      <SettingsContent settings={settings} setSettings={setSettings} variant="inline" />
    </div>
  );
}
