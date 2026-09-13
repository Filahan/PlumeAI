'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Plus } from 'lucide-react';
import ProviderOnboarding from '@/components/provider-onboarding';
import { useSettingsStore } from '@/lib/store-provider';
import { useAutomationsStore } from '@/lib/automations/store';

/** The `/` landing state: nothing selected yet. Until a provider key exists there is
 *  nothing an automation could run on, so the onboarding card takes the same slot. */
export default function AutomationsHome() {
  const router = useRouter();
  const { settings, setSettings, loaded } = useSettingsStore();
  const create = useAutomationsStore((s) => s.create);
  const listError = useAutomationsStore((s) => s.listError);
  const [creating, setCreating] = useState(false);

  const onNew = async () => {
    if (creating) return;
    setCreating(true);
    try {
      const id = await create();
      router.push(`/automations/${id}`);
    } catch {
      // surfaced by listError
      setCreating(false);
    }
  };

  if (!loaded) return <div className="flex-1" />;

  if (settings.providers.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 overflow-y-auto">
        <ProviderOnboarding settings={settings} setSettings={setSettings} />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/logo.png" alt="" className="h-9 w-auto mb-5 opacity-90" />
      <h1 className="text-[24px] font-semibold tracking-tight mb-1.5">
        What do you want to automate?
      </h1>
      <p className="text-[13px] text-[color:var(--muted-foreground)] max-w-[420px] mb-6">
        Chain your tools together on a schedule — search, summarize, filter, send. Pick an
        automation on the left, or start a new one.
      </p>
      <button
        type="button"
        onClick={() => void onNew()}
        disabled={creating}
        className="inline-flex items-center gap-1.5 h-10 px-4 rounded-full bg-[color:var(--primary)] text-white text-[13px] font-medium hover:opacity-90 disabled:opacity-40 transition"
      >
        <Plus size={15} strokeWidth={2} />
        New automation
      </button>
      {listError && <p className="mt-4 text-[12px] text-[#D4183D]">{listError}</p>}
    </div>
  );
}
