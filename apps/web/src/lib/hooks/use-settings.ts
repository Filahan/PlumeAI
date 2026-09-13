'use client';

import { useCallback, useEffect, useState } from 'react';
import type { Settings, SettingsSaveResult } from '@/lib/types';
import { settings as settingsApi } from '@/lib/api';

const DEFAULT_SETTINGS: Settings = {
  providers: [],
  defaultModel: { provider: 'openai', model: 'gpt-4o' },
  tools: {},
  toolCredentials: {},
  // Mirrors the API's own default, so the first PUT from a client that never finished
  // loading cannot silently rewrite the workspace's zone.
  timezone: 'UTC',
};

export function useSettings() {
  const [settings, setSettingsState] = useState<Settings>(DEFAULT_SETTINGS);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    settingsApi
      .get()
      .then((s) => {
        if (!cancelled) setSettingsState(s);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  /** Optimistic: the UI takes `next` immediately and the PUT follows.
   *
   *  Never rejects. The outcome comes back as a value so a caller that cares (the
   *  timezone picker) can surface a failure, while the many that don't stay exactly as
   *  they were — no unhandled rejection, no behaviour change. */
  const setSettings = useCallback(async (next: Settings): Promise<SettingsSaveResult> => {
    setSettingsState(next);
    try {
      await settingsApi.update(next);
      return { ok: true };
    } catch (e) {
      return {
        ok: false,
        error: e instanceof Error && e.message ? e.message : "Your settings couldn't be saved.",
      };
    }
  }, []);

  return { settings, setSettings, loaded };
}
