'use client';

import { useState } from 'react';
import { automations as automationsApi } from '@/lib/api';
import ScheduleDialog from '@/components/automations/inspector/schedule-dialog';
import type { ScheduleItem, Trigger } from '@/lib/automations/types';
import ScheduleRow from './schedule-row';
import { SCHEDULE_GRID, triggerOf } from './row-model';

const HEADERS = ['Automation', 'Runs', 'Next', 'Last result'];

/** Every schedule you have, soonest first — the server already sorts them.
 *
 *  The dialog lives here rather than in each row: one mounted editor, seeded from
 *  whichever row asked for it, so twenty rows do not mean twenty portals. */
export default function SchedulesTable({
  schedules,
  timezone,
  now,
  failures,
  busy,
  onToggle,
  onSaved,
}: {
  schedules: ScheduleItem[];
  timezone: string;
  now: number;
  failures: Record<string, number>;
  busy: boolean;
  onToggle(schedule: ScheduleItem, enabled: boolean): void;
  /** A schedule was rewritten — the board needs re-reading. */
  onSaved(): void;
}) {
  const [editing, setEditing] = useState<ScheduleItem | null>(null);

  const save = async (next: Trigger) => {
    if (!editing) return;
    await automationsApi.operations(editing.automationId, [{ op: 'set_trigger', trigger: next }]);
    onSaved();
  };

  return (
    <>
      <div className="overflow-hidden rounded-2xl border border-[color:var(--border)] bg-white">
        <div
          className={`${SCHEDULE_GRID} border-b border-[color:var(--border)] bg-[#FAFAFC] text-[11px] font-semibold uppercase tracking-[0.08em] text-[color:var(--muted-foreground)]`}
        >
          {HEADERS.map((header) => (
            <div key={header}>{header}</div>
          ))}
          <div className="text-right">On</div>
        </div>

        {schedules.map((schedule) => (
          <ScheduleRow
            key={schedule.automationId}
            schedule={schedule}
            timezone={timezone}
            now={now}
            failures={failures[schedule.automationId] ?? 0}
            busy={busy}
            onEdit={setEditing}
            onToggle={onToggle}
          />
        ))}
      </div>

      {editing && (
        <ScheduleDialog
          open
          onOpenChange={(next) => {
            if (!next) setEditing(null);
          }}
          automationName={editing.name}
          trigger={triggerOf(editing)}
          onSave={save}
        />
      )}
    </>
  );
}
