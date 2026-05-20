'use client';

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { Conversation, Message, Settings, ProviderConfig, UsageEntry, PROVIDER_NAMES, Provider } from '@/lib/types';
import { getCost, PricingMap } from '@/lib/pricing';

export type UsageWindow = '30m' | '1h' | '6h' | '24h';
export const USAGE_WINDOWS: { id: UsageWindow; label: string; ms: number }[] = [
  { id: '30m', label: '30m', ms: 30 * 60 * 1000 },
  { id: '1h', label: '1h', ms: 60 * 60 * 1000 },
  { id: '6h', label: '6h', ms: 6 * 60 * 60 * 1000 },
  { id: '24h', label: '24h', ms: 24 * 60 * 60 * 1000 },
];

const USAGE_WINDOW_KEY = 'webui-usage-window';
const PRICING_CACHE_KEY = 'webui-pricing-cache';
const PRICING_TTL_MS = 9 * 60 * 60 * 1000;
const OPENROUTER_MODELS_URL = 'https://openrouter.ai/api/v1/models';

// OpenRouter exposes Anthropic under simplified ids; map back to the SDK ids we send to Anthropic directly.
const ANTHROPIC_ALIAS: Record<string, string> = {
  'anthropic/claude-3.7-sonnet': 'claude-3-7-sonnet-20250219',
  'anthropic/claude-3.5-sonnet': 'claude-3-5-sonnet-20241022',
  'anthropic/claude-3.5-haiku': 'claude-3-5-haiku-20241022',
};

function usePricing(): PricingMap {
  const [pricing, setPricing] = useState<PricingMap>({});

  useEffect(() => {
    const cached = localStorage.getItem(PRICING_CACHE_KEY);
    if (cached) {
      try {
        const parsed = JSON.parse(cached) as { timestamp: number; data: PricingMap };
        if (parsed?.data && typeof parsed.data === 'object' && Date.now() - parsed.timestamp < PRICING_TTL_MS) {
          // eslint-disable-next-line react-hooks/set-state-in-effect
          setPricing(parsed.data);
          return;
        }
      } catch {
        // corrupt — fall through and refetch
      }
    }

    const controller = new AbortController();
    fetch(OPENROUTER_MODELS_URL, { signal: controller.signal })
      .then((r) => r.json())
      .then((json: { data?: Array<{ id: string; pricing?: { prompt?: string; completion?: string } }> }) => {
        const map: PricingMap = {};
        for (const m of json.data ?? []) {
          if (!m.id || !m.pricing) continue;
          const input = Number(m.pricing.prompt) * 1_000_000;
          const output = Number(m.pricing.completion) * 1_000_000;
          if (!Number.isFinite(input) || !Number.isFinite(output)) continue;
          map[m.id] = { input, output };
          if (m.id.startsWith('openai/')) map[m.id.slice('openai/'.length)] = { input, output };
          if (ANTHROPIC_ALIAS[m.id]) map[ANTHROPIC_ALIAS[m.id]] = { input, output };
        }
        setPricing(map);
        localStorage.setItem(PRICING_CACHE_KEY, JSON.stringify({ timestamp: Date.now(), data: map }));
      })
      .catch(() => {
        // network or CORS error — pricing stays empty until next attempt
      });

    return () => controller.abort();
  }, []);

  return pricing;
}

const STORAGE_DEBOUNCE_MS = 250;

function newId(): string {
  return crypto.randomUUID();
}

function getDefaultTitle(content: string): string {
  return content.slice(0, 40) + (content.length > 40 ? '...' : '');
}

function useDebouncedPersist<T>(key: string, value: T, enabled: boolean) {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!enabled) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      localStorage.setItem(key, JSON.stringify(value));
    }, STORAGE_DEBOUNCE_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [key, value, enabled]);
}

export function useConversations() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem('webui-conversations');
    if (saved) {
      try {
        const parsed = JSON.parse(saved) as Conversation[];
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setConversations(parsed);
      } catch {
        // corrupt payload — ignore and start fresh
      }
    }
    setLoaded(true);
  }, []);

  useDebouncedPersist('webui-conversations', conversations, loaded);

  const createConversation = useCallback((provider: Provider, model: string) => {
    const conv: Conversation = {
      id: newId(),
      title: 'Nouvelle conversation',
      messages: [],
      createdAt: Date.now(),
      updatedAt: Date.now(),
      provider,
      model,
    };
    setConversations((prev) => [conv, ...prev]);
    return conv.id;
  }, []);

  const addMessage = useCallback(
    (conversationId: string, message: Omit<Message, 'id' | 'timestamp'>) => {
      const msg: Message = { ...message, id: newId(), timestamp: Date.now() };
      setConversations((prev) =>
        prev.map((c) => {
          if (c.id !== conversationId) return c;
          const isFirstUserMessage = c.messages.length === 0 && msg.role === 'user';
          return {
            ...c,
            messages: [...c.messages, msg],
            title: isFirstUserMessage ? getDefaultTitle(msg.content) : c.title,
            updatedAt: Date.now(),
          };
        })
      );
      return msg.id;
    },
    []
  );

  const updateMessage = useCallback(
    (conversationId: string, messageId: string, chunk: string, replace = false) => {
      setConversations((prev) =>
        prev.map((c) => {
          if (c.id !== conversationId) return c;
          return {
            ...c,
            messages: c.messages.map((m) =>
              m.id === messageId ? { ...m, content: replace ? chunk : m.content + chunk } : m
            ),
            updatedAt: Date.now(),
          };
        })
      );
    },
    []
  );

  const deleteConversation = useCallback((id: string) => {
    setConversations((prev) => prev.filter((c) => c.id !== id));
  }, []);

  const renameConversation = useCallback((id: string, title: string) => {
    if (!title) return;
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...c, title, updatedAt: Date.now() } : c))
    );
  }, []);

  const setConversationModel = useCallback(
    (id: string, provider: Conversation['provider'], model: string) => {
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? { ...c, provider, model, updatedAt: Date.now() } : c))
      );
    },
    []
  );

  return {
    conversations,
    createConversation,
    addMessage,
    updateMessage,
    deleteConversation,
    renameConversation,
    setConversationModel,
    loaded,
  };
}

export function useUsage() {
  const pricing = usePricing();
  const [usageLog, setUsageLog] = useState<UsageEntry[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [window, setWindowState] = useState<UsageWindow>('30m');

  useEffect(() => {
    const saved = localStorage.getItem('webui-usage');
    if (saved) {
      try {
        const parsed = JSON.parse(saved) as UsageEntry[];
        // Keep enough history to satisfy the longest window we offer (24h)
        const longest = USAGE_WINDOWS[USAGE_WINDOWS.length - 1].ms;
        const cutoff = Date.now() - longest;
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setUsageLog(parsed.filter((e) => e.timestamp >= cutoff));
      } catch {
        // corrupt payload — start fresh
      }
    }
    const savedWindow = localStorage.getItem(USAGE_WINDOW_KEY);
    if (savedWindow && USAGE_WINDOWS.some((w) => w.id === savedWindow)) {
      setWindowState(savedWindow as UsageWindow);
    }
    setLoaded(true);
  }, []);

  useDebouncedPersist('webui-usage', usageLog, loaded);

  useEffect(() => {
    if (!loaded) return;
    localStorage.setItem(USAGE_WINDOW_KEY, window);
  }, [window, loaded]);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);

  const recordUsage = useCallback((entry: Omit<UsageEntry, 'timestamp'>) => {
    setUsageLog((prev) => [...prev, { ...entry, timestamp: Date.now() }]);
  }, []);

  const setWindow = useCallback((w: UsageWindow) => setWindowState(w), []);

  const recentUsage = useMemo(() => {
    const windowMs = USAGE_WINDOWS.find((w) => w.id === window)?.ms ?? USAGE_WINDOWS[0].ms;
    const cutoff = now - windowMs;
    let tokens = 0;
    let cost = 0;
    for (const e of usageLog) {
      if (e.timestamp < cutoff) continue;
      tokens += e.inputTokens + e.outputTokens;
      cost += getCost(pricing, e.model, e.inputTokens, e.outputTokens);
    }
    return { tokens, cost };
  }, [usageLog, now, pricing, window]);

  const usageForConversation = useCallback(
    (conversationId: string | null) => {
      if (!conversationId) return { tokens: 0, cost: 0 };
      let tokens = 0;
      let cost = 0;
      for (const e of usageLog) {
        if (e.conversationId !== conversationId) continue;
        tokens += e.inputTokens + e.outputTokens;
        cost += getCost(pricing, e.model, e.inputTokens, e.outputTokens);
      }
      return { tokens, cost };
    },
    [usageLog, pricing]
  );

  return { recordUsage, recentUsage, usageForConversation, window, setWindow, usageLog, pricing, loaded };
}

const DEFAULT_SETTINGS: Settings = {
  providers: [],
  defaultModel: { provider: 'openai', model: 'gpt-4o' },
};

function migrateSettings(raw: unknown): Settings {
  if (!raw || typeof raw !== 'object') return DEFAULT_SETTINGS;
  const r = raw as Partial<Settings> & { provider?: Provider; model?: string; apiKey?: string };
  // Already in new shape
  if (Array.isArray(r.providers) && r.defaultModel) {
    return { providers: r.providers, defaultModel: r.defaultModel };
  }
  // Legacy shape: { provider, model, apiKey }
  if (r.provider && r.model) {
    const providers: ProviderConfig[] = r.apiKey
      ? [{ id: newId(), provider: r.provider, label: PROVIDER_NAMES[r.provider], apiKey: r.apiKey }]
      : [];
    return { providers, defaultModel: { provider: r.provider, model: r.model } };
  }
  return DEFAULT_SETTINGS;
}

export function useSettings() {
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem('webui-settings');
    if (saved) {
      try {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setSettings(migrateSettings(JSON.parse(saved)));
      } catch {
        // corrupt payload — keep defaults
      }
    }
    setLoaded(true);
  }, []);

  useDebouncedPersist('webui-settings', settings, loaded);

  return { settings, setSettings, loaded };
}
