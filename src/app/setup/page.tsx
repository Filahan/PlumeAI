'use client';

import { useRouter } from 'next/navigation';
import { useSettingsStore } from '@/lib/store-provider';
import SettingsContent from '@/components/settings-content';
import { ProviderLogo, PROVIDER_ACCENT } from '@/components/provider-logo';
import { ArrowRight } from 'lucide-react';

export default function SetupPage() {
  const router = useRouter();
  const { settings, setSettings } = useSettingsStore();
  const canStart = settings.providers.length > 0;

  return (
    <div className="fixed inset-0 flex items-center justify-center px-6">
      <div className="w-full max-w-[520px] rounded-3xl border border-[color:var(--border)] bg-white p-8">
        <div className="text-center mb-6">
          <div className="inline-flex items-center justify-center gap-2 mb-4">
            <ProviderLogo provider="openai" size={22} className={PROVIDER_ACCENT.openai} />
            <ProviderLogo provider="anthropic" size={22} className={PROVIDER_ACCENT.anthropic} />
            <ProviderLogo provider="openrouter" size={22} className={PROVIDER_ACCENT.openrouter} />
          </div>
          <h1 className="text-[22px] font-semibold mb-1 tracking-tight">Connect a provider</h1>
          <p className="text-[13px] text-[color:var(--muted-foreground)]">
            Add one or more API keys to get started. They&apos;re encrypted at rest.
          </p>
        </div>

        <SettingsContent settings={settings} setSettings={setSettings} variant="inline" />

        <button
          type="button"
          onClick={() => router.push('/')}
          disabled={!canStart}
          className="mt-6 w-full inline-flex items-center justify-center gap-2 h-11 rounded-full bg-[color:var(--primary)] text-white text-[13px] font-semibold hover:opacity-90 transition disabled:opacity-30 disabled:cursor-not-allowed"
        >
          Start chatting
          <ArrowRight size={16} strokeWidth={2.5} />
        </button>
      </div>
    </div>
  );
}
