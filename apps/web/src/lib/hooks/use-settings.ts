'use client';

import { useCallback, useEffect, useState } from 'react';
import { Settings } from '@/lib/types';
import { settings as settingsApi } from '@/lib/api';

const DEFAULT_SETTINGS: Settings = {
  providers: [],
  defaultModel: { provider: 'openai', model: 'gpt-4o' },
  tools: {},
  toolCredentials: {},
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

  const setSettings = useCallback((next: Settings) => {
    setSettingsState(next);
    settingsApi.update(next).catch(() => {});
  }, []);

  return { settings, setSettings, loaded };
}
