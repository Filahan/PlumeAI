'use client';

import { createContext, useContext, ReactNode, useState, useEffect, useCallback } from 'react';
import { useConversations, useSettings, useUsage } from '@/lib/store';

const SIDEBAR_OPEN_KEY = 'webui-sidebar-open';

type ConversationsValue = ReturnType<typeof useConversations>;
type SettingsValue = ReturnType<typeof useSettings>;
type UsageValue = ReturnType<typeof useUsage>;
type SidebarValue = { open: boolean; toggle: () => void };

const ConversationsContext = createContext<ConversationsValue | null>(null);
const SettingsContext = createContext<SettingsValue | null>(null);
const UsageContext = createContext<UsageValue | null>(null);
const SidebarContext = createContext<SidebarValue | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const conversations = useConversations();
  const settings = useSettings();
  const usage = useUsage();

  const [open, setOpen] = useState(true);
  useEffect(() => {
    const saved = localStorage.getItem(SIDEBAR_OPEN_KEY);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (saved !== null) setOpen(saved === 'true');
  }, []);
  useEffect(() => {
    localStorage.setItem(SIDEBAR_OPEN_KEY, String(open));
  }, [open]);
  const toggle = useCallback(() => setOpen((v) => !v), []);

  return (
    <ConversationsContext.Provider value={conversations}>
      <SettingsContext.Provider value={settings}>
        <UsageContext.Provider value={usage}>
          <SidebarContext.Provider value={{ open, toggle }}>
            {children}
          </SidebarContext.Provider>
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

export function useSidebarStore(): SidebarValue {
  const ctx = useContext(SidebarContext);
  if (!ctx) throw new Error('useSidebarStore must be used inside <StoreProvider>');
  return ctx;
}
