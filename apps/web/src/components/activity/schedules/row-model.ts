/** Shared shape of the schedule list: the one grid the header and every row use, and the
 *  trigger a row stands for. Pure — no React. */

import type { ScheduleItem, Trigger } from '@/lib/automations/types';

/** Automation · Runs · Next · Last result · On. Defined once so a column added to the
 *  header cannot quietly fall out of step with the rows underneath it. */
export const SCHEDULE_GRID =
  'grid grid-cols-[minmax(0,1fr)_230px_160px_150px_70px] items-center gap-4 px-4 py-3';

/** The `Trigger` a schedule row already knows, without loading its document.
 *
 *  `GET /schedules` flattens `mode` / `cron` / `everyMinutes` / `timezone` out of the
 *  stored trigger precisely so the editor can be opened from here; rebuilding it costs
 *  nothing and keeps the dialog's input identical to the inspector's. */
export function triggerOf(schedule: ScheduleItem): Trigger {
  if (schedule.mode === 'interval') {
    return {
      type: 'schedule',
      settings: { mode: 'interval', every_minutes: schedule.everyMinutes ?? 15 },
    };
  }
  return {
    type: 'schedule',
    settings: { mode: 'cron', cron: schedule.cron ?? '0 9 * * *', timezone: schedule.timezone },
  };
}
