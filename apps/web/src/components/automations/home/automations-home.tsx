'use client';

import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, Plus, Sparkles } from 'lucide-react';
import ProviderOnboarding from '@/components/provider-onboarding';
import { useSettingsStore } from '@/lib/store-provider';
import { useAutomationsStore } from '@/lib/automations/store';

/** The describe-box grows to a few lines, then scrolls. */
const MAX_HEIGHT = 160;

/** The `/` landing state: nothing selected yet. Until a provider key exists there is
 *  nothing an automation could run on, so the onboarding card takes the same slot.
 *
 *  The primary way in is describing the automation in words: that creates an empty
 *  automation, opens its editor with the assistant drawer, and sends the text as the
 *  first message (handed over through the store — see `assistant.pendingFirstMessage`). */
export default function AutomationsHome() {
  const router = useRouter();
  const { settings, setSettings, loaded } = useSettingsStore();
  const create = useAutomationsStore((s) => s.create);
  const setAssistantFirstMessage = useAutomationsStore((s) => s.setAssistantFirstMessage);
  const listError = useAutomationsStore((s) => s.listError);
  const [creating, setCreating] = useState(false);
  const [text, setText] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, MAX_HEIGHT)}px`;
  }, [text]);

  /** `first` is sent by the editor once it has loaded; without it this is a blank start. */
  const start = async (first: string) => {
    if (creating) return;
    setCreating(true);
    try {
      const id = await create();
      if (first) setAssistantFirstMessage(first);
      router.push(`/automations/${id}`);
    } catch {
      // surfaced by listError
      setCreating(false);
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== 'Enter' || e.shiftKey) return;
    e.preventDefault();
    if (text.trim()) void start(text.trim());
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
        Describe it in a sentence — the assistant builds the trigger and the steps, and you
        can edit anything it made.
      </p>

      <div className="w-full max-w-[560px]">
        <div className="flex items-end gap-2 rounded-2xl border border-[color:var(--border)] bg-white px-3 py-2.5 text-left focus-within:border-[color:var(--foreground)]/30 transition-colors">
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            disabled={creating}
            placeholder="Describe what you want to automate…"
            aria-label="Describe what you want to automate"
            className="min-w-0 flex-1 resize-none bg-transparent text-[14px] leading-relaxed outline-none placeholder:text-[color:var(--muted-foreground)] disabled:opacity-60"
          />
          <button
            type="button"
            onClick={() => void start(text.trim())}
            disabled={creating || text.trim().length === 0}
            className="shrink-0 inline-flex items-center gap-1.5 h-8 px-3 rounded-full bg-[color:var(--primary)] text-white text-[12px] font-medium hover:opacity-90 disabled:opacity-30 transition"
          >
            {creating ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <Sparkles size={13} strokeWidth={2} />
            )}
            Create
          </button>
        </div>

        <div className="mt-3 flex items-center justify-center">
          <button
            type="button"
            onClick={() => void start('')}
            disabled={creating}
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-full text-[12px] font-medium text-[color:var(--muted-foreground)] hover:bg-[color:var(--surface-muted)] hover:text-[color:var(--foreground)] disabled:opacity-40 transition"
          >
            <Plus size={14} strokeWidth={2} />
            New automation
          </button>
        </div>
      </div>

      {listError && <p className="mt-4 text-[12px] text-[#D4183D]">{listError}</p>}
    </div>
  );
}
