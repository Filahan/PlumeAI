'use client';

import { useMemo, useState } from 'react';
import { CalendarClock, Pencil } from 'lucide-react';
import { useAutomationsStore, useCurrentAutomation } from '@/lib/automations/store';
import type { Operation, Trigger } from '@/lib/automations/types';
import ScheduleDialog from './schedule-dialog';
import { browserTimezone } from './next-runs';
import { draftFromTrigger, draftSentence } from './schedule-draft';

/** How the automation starts, as one sentence plus a way to change it.
 *
 *  The editing itself lives in `ScheduleDialog`, which the Schedules tab opens too — a
 *  320px rail is the wrong place to lay out "every weekday at 08:00 in Europe/Paris", and
 *  two copies of that reasoning would have drifted apart. Saving is still one
 *  `set_trigger`: one user gesture, one operation, one version. */
export default function TriggerForm() {
  const current = useCurrentAutomation();
  const applyOperations = useAutomationsStore((s) => s.applyOperations);
  const fallbackTimezone = useMemo(() => browserTimezone(), []);
  const [open, setOpen] = useState(false);

  // The store's own object, not a fallback built here: a fresh `{type: 'manual'}` every
  // render would re-run the memo every render.
  const trigger = current?.document.trigger ?? null;
  const sentence = useMemo(
    () => draftSentence(draftFromTrigger(trigger, fallbackTimezone)),
    [trigger, fallbackTimezone]
  );

  if (!current || !trigger) return null;

  const save = (next: Trigger) => {
    const op: Operation = { op: 'set_trigger', trigger: next };
    return applyOperations([op]);
  };

  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2 rounded-xl border border-[color:var(--border)] bg-[#FAFAFC] px-3 py-2.5">
        <CalendarClock
          size={14}
          strokeWidth={1.75}
          aria-hidden
          className="mt-px shrink-0 text-[color:var(--muted-foreground)]"
        />
        <p className="min-w-0 text-[12px] leading-[18px]">{sentence}</p>
      </div>

      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex h-8 w-full items-center justify-center gap-1.5 rounded-lg border border-[color:var(--border)] bg-white text-[12px] font-medium outline-none transition-colors hover:bg-[color:var(--surface-muted)] focus-visible:ring-3 focus-visible:ring-[color:var(--ring)]/50"
      >
        <Pencil size={12} strokeWidth={1.75} aria-hidden />
        Edit schedule
      </button>

      <ScheduleDialog
        open={open}
        onOpenChange={setOpen}
        automationName={current.document.name}
        trigger={trigger}
        onSave={save}
      />
    </div>
  );
}
