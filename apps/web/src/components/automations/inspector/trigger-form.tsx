'use client';

import { useMemo } from 'react';
import { CalendarClock, Hand, Timer } from 'lucide-react';
import { useAutomationsStore, useCurrentAutomation } from '@/lib/automations/store';
import type { Operation, Trigger } from '@/lib/automations/types';
import LabeledField from './labeled-field';
import NextRunsPreview from './next-runs-preview';
import ScheduleFields from './schedule-fields';
import { TextField } from './text-field';
import { browserTimezone, nextCronRuns, nextIntervalRuns, parseCronPreset } from './next-runs';

type Mode = 'manual' | 'interval' | 'schedule';

const MODES: { id: Mode; label: string; hint: string; icon: typeof Hand }[] = [
  { id: 'manual', label: 'When I press Run', hint: 'Nothing happens on its own', icon: Hand },
  { id: 'interval', label: 'Every few minutes', hint: 'A simple repeating loop', icon: Timer },
  { id: 'schedule', label: 'On a schedule', hint: 'At a set time of day', icon: CalendarClock },
];

const QUICK_MINUTES = [5, 15, 30, 60];
const DEFAULT_CRON = '0 9 * * *';
const DEFAULT_MINUTES = 15;

/** How the automation starts. One gesture = one `set_trigger`, and the payload always
 *  carries exactly one of `cron` / `every_minutes` — the document schema rejects both. */
export default function TriggerForm() {
  const current = useCurrentAutomation();
  const applyOperations = useAutomationsStore((s) => s.applyOperations);
  const fallbackTimezone = useMemo(() => browserTimezone(), []);

  if (!current) return null;
  const trigger = current.document.trigger;
  const settings = trigger.type === 'schedule' ? trigger.settings : null;
  const mode: Mode =
    trigger.type === 'manual' ? 'manual' : settings?.mode === 'interval' ? 'interval' : 'schedule';

  const cron = settings?.mode === 'cron' ? settings.cron : DEFAULT_CRON;
  const everyMinutes = settings?.mode === 'interval' ? settings.every_minutes : DEFAULT_MINUTES;
  const timezone = settings?.timezone ?? fallbackTimezone;
  const shape = parseCronPreset(cron);

  const commit = (next: Trigger) => {
    const op: Operation = { op: 'set_trigger', trigger: next };
    void applyOperations([op]).catch(() => {
      // surfaced through `current.saveError`
    });
  };

  const setCron = (nextCron: string, nextTimezone: string) =>
    commit({
      type: 'schedule',
      settings: { mode: 'cron', cron: nextCron, timezone: nextTimezone },
    });

  const setEvery = (minutes: number) =>
    commit({
      type: 'schedule',
      settings: { mode: 'interval', every_minutes: Math.min(10080, Math.max(1, minutes)) },
    });

  const switchMode = (next: Mode) => {
    if (next === mode) return;
    if (next === 'manual') commit({ type: 'manual' });
    else if (next === 'interval') setEvery(everyMinutes);
    else setCron(cron, timezone);
  };

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        {MODES.map((m) => {
          const Icon = m.icon;
          const active = m.id === mode;
          return (
            <button
              key={m.id}
              type="button"
              onClick={() => switchMode(m.id)}
              aria-pressed={active}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl border bg-white text-left transition ${
                active
                  ? 'border-[color:var(--foreground)]/30 shadow-[0_1px_2px_rgba(0,0,0,0.06)]'
                  : 'border-[color:var(--border)] hover:bg-[color:var(--surface-muted)]/60'
              }`}
            >
              <Icon size={14} strokeWidth={1.75} className="shrink-0" />
              <span className="min-w-0">
                <span className="block text-[12px] font-medium truncate">{m.label}</span>
                <span className="block text-[11px] text-[color:var(--muted-foreground)] truncate">
                  {m.hint}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      {mode === 'interval' && (
        <LabeledField label="Run every">
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <div className="w-[86px]">
                <TextField
                  type="number"
                  min={1}
                  max={10080}
                  value={String(everyMinutes)}
                  aria-label="Minutes between runs"
                  onChange={() => {}}
                  onFlush={(text) => {
                    const parsed = Number(text.trim());
                    if (Number.isFinite(parsed) && Math.round(parsed) !== everyMinutes) {
                      setEvery(Math.round(parsed));
                    }
                  }}
                />
              </div>
              <span className="text-[12px] text-[color:var(--muted-foreground)]">minutes</span>
            </div>
            <div className="flex flex-wrap gap-1">
              {QUICK_MINUTES.map((minutes) => (
                <button
                  key={minutes}
                  type="button"
                  onClick={() => setEvery(minutes)}
                  className={`h-6 px-2 rounded-full border text-[11px] font-medium transition ${
                    minutes === everyMinutes
                      ? 'border-[color:var(--foreground)]/30 bg-[color:var(--surface-muted)]'
                      : 'border-[color:var(--border)] hover:bg-[color:var(--surface-muted)]'
                  }`}
                >
                  {minutes === 60 ? '1 hour' : `${minutes} min`}
                </button>
              ))}
            </div>
          </div>
        </LabeledField>
      )}

      {mode === 'schedule' && (
        <ScheduleFields cron={cron} timezone={timezone} onChange={setCron} />
      )}

      {mode === 'interval' && (
        <NextRunsPreview
          runs={nextIntervalRuns(everyMinutes)}
          timezone={fallbackTimezone}
          approximate
        />
      )}
      {mode === 'schedule' && (
        <NextRunsPreview
          runs={shape ? nextCronRuns(shape, timezone) : []}
          timezone={timezone}
        />
      )}
    </div>
  );
}
