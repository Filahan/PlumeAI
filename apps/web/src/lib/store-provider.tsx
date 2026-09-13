'use client';

import { createContext, useContext, ReactNode } from 'react';
import { useSettings } from '@/lib/hooks/use-settings';
import { useUsage } from '@/lib/hooks/use-usage';

type SettingsValue = ReturnType<typeof useSettings>;
type UsageValue = ReturnType<typeof useUsage>;

const SettingsContext = createContext<SettingsValue | null>(null);
const UsageContext = createContext<UsageValue | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const settings = useSettings();
  const usage = useUsage();

  return (
    <SettingsContext.Provider value={settings}>
      <UsageContext.Provider value={usage}>
        {children}
      </UsageContext.Provider>
    </SettingsContext.Provider>
  );
}

export function useSettingsStore(): SettingsValue {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error('useSettingsStore must be used inside <StoreProvider>');
  return ctx;
}

export function useUsageStore(): UsageValue {
  const ctx = useContext(UsageContext);
  if (!ctx) throw new Error('useUsageStore must be used inside <StoreProvider>');
  return ctx;
}
