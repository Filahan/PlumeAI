'use client';

import { createContext, useContext, ReactNode } from 'react';
import { useConversations, useSettings, useUsage } from '@/lib/store';

type ConversationsValue = ReturnType<typeof useConversations>;
type SettingsValue = ReturnType<typeof useSettings>;
type UsageValue = ReturnType<typeof useUsage>;

const ConversationsContext = createContext<ConversationsValue | null>(null);
const SettingsContext = createContext<SettingsValue | null>(null);
const UsageContext = createContext<UsageValue | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const conversations = useConversations();
  const settings = useSettings();
  const usage = useUsage();

  return (
    <ConversationsContext.Provider value={conversations}>
      <SettingsContext.Provider value={settings}>
        <UsageContext.Provider value={usage}>
          {children}
        </UsageContext.Provider>
      </SettingsContext.Provider>
    </ConversationsContext.Provider>
  );
}

export function useConversationsStore(): ConversationsValue {
  const ctx = useContext(ConversationsContext);
  if (!ctx) throw new Error('useConversationsStore must be used inside <StoreProvider>');
  return ctx;
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
