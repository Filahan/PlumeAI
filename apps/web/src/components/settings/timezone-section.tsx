'use client';

import { useMemo, useState } from 'react';
import { AlertCircle, Globe } from 'lucide-react';
import type { SetSettings, Settings } from '@/lib/types';
import TimezonePicker from '@/components/automations/inspector/timezone-picker';
import { browserTimezone } from '@/components/automations/inspector/next-runs';

/** The workspace's IANA zone.
 *
 *  Nothing here is state of its own: the value rides on `Settings` and is written through
 *  the same whole-object PUT as every other setting. That PUT can fail (the API validates
 *  the zone), so the result is awaited and shown rather than dropped. */
export default function TimezoneSection({
  settings,
  setSettings,
}: {
  settings: Settings;
  setSettings: SetSettings;
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

  const [error, setError] = useState<string | null>(null);

  // `GET /settings` always answers with a zone, so this fallback only covers the moments
  // it cannot: before the first load lands, or a payload stored before the field existed.
  const value = settings.timezone || browser;

  const commit = async (next: string) => {
    setError(null);
    const result = await setSettings({ ...settings, timezone: next });
    if (result && !result.ok) setError(result.error);
  };

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
        onChange={(next) => void commit(next)}
      />

      {error && (
        <p role="alert" className="flex items-start gap-1.5 text-[11px] text-[#D4183D] leading-relaxed">
          <AlertCircle size={12} strokeWidth={2.25} className="mt-px shrink-0" />
          <span className="break-words">{error}</span>
        </p>
      )}

      <p className="text-[11px] text-[#a8a8a8] leading-relaxed">
        Used for schedules that don&apos;t set their own timezone, and for dates given to the AI.
        {value !== browser && (
          <>
            {' '}
            Your browser is in{' '}
            <button
              type="button"
              onClick={() => void commit(browser)}
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
