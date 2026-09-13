'use client';

import { useMemo } from 'react';
import { Globe } from 'lucide-react';
import type { Settings } from '@/lib/types';
import TimezonePicker from '@/components/automations/inspector/timezone-picker';
import { browserTimezone } from '@/components/automations/inspector/next-runs';

/** The workspace's IANA zone.
 *
 *  Nothing here is workspace-specific state of its own: the value rides on `Settings`
 *  and is written through the same whole-object PUT as every other setting. */
export default function TimezoneSection({
  settings,
  setSettings,
}: {
  settings: Settings;
  setSettings: (s: Settings) => void;
}) {
  const browser = useMemo(() => browserTimezone(), []);
  const zones = useMemo(() => {
    try {
      return Intl.supportedValuesOf('timeZone');
    } catch {
      // Older engines have no zone list; a two-entry combobox still lets the user pick.
      return Array.from(new Set([browser, 'UTC']));
    }
  }, [browser]);

  // A workspace that has never chosen one shows the browser's zone rather than the
  // server's `"UTC"` placeholder — it is almost always the answer the user wants.
  const value = settings.timezone || browser;

  return (
    <section className="space-y-2">
      <div className="flex items-center gap-2">
        <Globe size={15} strokeWidth={2} className="text-[#8e8e8e] shrink-0" />
        <h3 className="text-[13px] font-medium text-[#1c1c1c]">Timezone</h3>
      </div>

      <TimezonePicker
        id="workspace-timezone"
        value={value}
        zones={zones}
        onChange={(next) => setSettings({ ...settings, timezone: next })}
      />

      <p className="text-[11px] text-[#a8a8a8] leading-relaxed">
        Used for schedules that don&apos;t set their own timezone, and for dates given to the AI.
        {value !== browser && (
          <>
            {' '}
            Your browser is in{' '}
            <button
              type="button"
              onClick={() => setSettings({ ...settings, timezone: browser })}
              className="underline underline-offset-2 hover:text-[#1c1c1c] transition"
            >
              {browser}
            </button>
            .
          </>
        )}
      </p>
    </section>
  );
}
