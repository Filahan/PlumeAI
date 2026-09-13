'use client';

import { useMemo, useState } from 'react';
import { Code2 } from 'lucide-react';
import { Input } from '@/components/ui/input';
import type { Trigger } from '@/lib/automations/types';
import ScheduleModeCards from './schedule-mode-cards';
import SchedulePreview from './schedule-preview';
import ScheduleSentence from './schedule-sentence';
import {
  draftCaveat,
  draftCron,
  draftFromTrigger,
  draftToTrigger,
  type ScheduleDraft,
} from './schedule-draft';
import {
  browserTimezone,
  nextCronRuns,
  nextIntervalRuns,
  parseCronPreset,
} from './next-runs';

/** Everything inside the schedule dialog below its title.
 *
 *  Split from the dialog shell so it mounts fresh every time the dialog opens: the draft
 *  is seeded from the trigger in `useState`, and a body that survived a close would keep
 *  edits nobody saved. Nothing here writes — `onSave` owns that, and the caller decides
 *  whether that is a store operation or a direct API call. */
export default function ScheduleDialogBody({
  trigger,
  onSave,
  onCancel,
}: {
  trigger: Trigger;
  onSave(next: Trigger): void | Promise<void>;
  onCancel(): void;
}) {
  const fallbackTimezone = useMemo(() => browserTimezone(), []);
  const [draft, setDraft] = useState<ScheduleDraft>(() =>
    draftFromTrigger(trigger, fallbackTimezone)
  );
  /** Frozen for the life of the dialog: "Tomorrow" must not become "Today" mid-edit. */
  const [now] = useState(() => Date.now());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const timezones = useMemo(() => {
    try {
      return Intl.supportedValuesOf('timeZone');
    } catch {
      return [fallbackTimezone, 'UTC'];
    }
  }, [fallbackTimezone]);

  const runs = useMemo(() => {
    if (draft.mode === 'manual') return [];
    if (draft.mode === 'interval') return nextIntervalRuns(draft.everyMinutes);
    const shape = parseCronPreset(draftCron(draft));
    return shape ? nextCronRuns(shape, draft.timezone, 3, now) : [];
  }, [draft, now]);

  const patch = (next: Partial<ScheduleDraft>) => setDraft((current) => ({ ...current, ...next }));

  const cronText = draftCron(draft);
  const cronBroken =
    draft.mode === 'cron' && draft.custom && cronText.split(/\s+/).filter(Boolean).length !== 5;

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSave(draftToTrigger(draft));
      onCancel();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That change was not accepted.');
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-[18px]">
      <ScheduleModeCards mode={draft.mode} onChange={(mode) => patch({ mode })} />

      {draft.mode === 'manual' ? (
        <p className="rounded-2xl border border-[color:var(--border)] bg-[#FAFAFC] p-4 text-[13px] leading-5 text-[color:var(--muted-foreground)]">
          Nothing starts this automation on its own. It waits for you to press Run — and it
          keeps whatever schedule you set here the next time you want one.
        </p>
      ) : (
        <ScheduleSentence draft={draft} timezones={timezones} onChange={patch} />
      )}

      {draft.mode !== 'manual' && (
        <SchedulePreview
          runs={runs}
          timezone={draft.mode === 'interval' ? fallbackTimezone : draft.timezone}
          now={now}
          caveat={draftCaveat(draft)}
        />
      )}

      {draft.mode === 'cron' && draft.custom && (
        <div className="flex flex-col gap-1">
          <Input
            aria-label="Cron expression"
            value={draft.cron}
            onChange={(e) => patch({ cron: e.target.value })}
            className="h-8 rounded-lg border-[color:var(--border)] bg-white font-mono text-[12px] md:text-[12px]"
          />
          <p className="text-[11px] text-[color:var(--muted-foreground)]">
            Five fields: minute, hour, day of month, month, weekday.
          </p>
        </div>
      )}

      {error && <p className="text-[12px] text-[#D4183D]">{error}</p>}

      <div className="flex items-center justify-between gap-3 border-t border-[color:var(--border)] pt-3">
        {draft.mode === 'cron' ? (
          <button
            type="button"
            aria-pressed={draft.custom}
            onClick={() => patch({ custom: !draft.custom, cron: cronText })}
            className={`flex items-center gap-1.5 rounded-lg px-1 py-1 text-[12px] outline-none transition-colors focus-visible:ring-3 focus-visible:ring-[color:var(--ring)]/50 ${
              draft.custom
                ? 'text-[color:var(--foreground)]'
                : 'text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)]'
            }`}
          >
            <Code2 size={13} strokeWidth={1.75} aria-hidden />
            Write it as cron
          </button>
        ) : (
          <span />
        )}

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="flex h-8 items-center rounded-[10px] border border-[color:var(--border)] px-3.5 text-[13px] font-medium outline-none transition-colors hover:bg-[color:var(--surface-muted)] focus-visible:ring-3 focus-visible:ring-[color:var(--ring)]/50"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={saving || cronBroken}
            onClick={() => void save()}
            className="flex h-8 items-center rounded-[10px] bg-[color:var(--primary)] px-4 text-[13px] font-medium text-[color:var(--primary-foreground)] outline-none transition-opacity hover:opacity-90 focus-visible:ring-3 focus-visible:ring-[color:var(--ring)]/50 disabled:pointer-events-none disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save schedule'}
          </button>
        </div>
      </div>
    </div>
  );
}
