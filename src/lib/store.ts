'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { Conversation, Message, Settings, UsageEntry, Provider } from '@/lib/types';
import { deleteBlobs } from '@/lib/blob-store';
import { getCost, PricingMap } from '@/lib/pricing';
import {
  listConversations as listConversationsAction,
  createConversation as createConversationAction,
  addMessage as addMessageAction,
  updateMessage as updateMessageAction,
  renameConversation as renameConversationAction,
  setConversationModel as setConversationModelAction,
  deleteConversation as deleteConversationAction,
} from '@/lib/actions/conversations';
import {
  getSettings as getSettingsAction,
  updateSettings as updateSettingsAction,
} from '@/lib/actions/settings';
import {
  listUsage as listUsageAction,
  recordUsage as recordUsageAction,
} from '@/lib/actions/usage';

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
      .catch(() => {});

    return () => controller.abort();
  }, []);

  return pricing;
}

function newId(): string {
  return crypto.randomUUID();
}

export function useConversations() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listConversationsAction()
      .then((rows) => {
        if (cancelled) return;
        setConversations(rows);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const createConversation = useCallback((provider: Provider, model: string) => {
    const id = newId();
    const now = Date.now();
    const conv: Conversation = {
      id,
      title: 'Nouvelle conversation',
      messages: [],
      createdAt: now,
      updatedAt: now,
      provider,
      model,
    };
    // Optimistic insert; server will assign its own id, so we replace the optimistic record on response.
    setConversations((prev) => [conv, ...prev]);
    createConversationAction(provider, model)
      .then((real) => {
        setConversations((prev) => prev.map((c) => (c.id === id ? real : c)));
      })
      .catch(() => {
        // rollback the optimistic insert on failure
        setConversations((prev) => prev.filter((c) => c.id !== id));
      });
    return id;
  }, []);

  const addMessage = useCallback(
    (conversationId: string, message: Omit<Message, 'id' | 'timestamp'>) => {
      const tempId = newId();
      const now = Date.now();
      const msg: Message = { ...message, id: tempId, timestamp: now };
      setConversations((prev) =>
        prev.map((c) => {
          if (c.id !== conversationId) return c;
          const isFirstUserMessage = c.messages.length === 0 && msg.role === 'user';
          return {
            ...c,
            messages: [...c.messages, msg],
            title: isFirstUserMessage
              ? message.content.slice(0, 40) + (message.content.length > 40 ? '...' : '')
              : c.title,
            updatedAt: now,
          };
        })
      );
      addMessageAction(conversationId, message)
        .then(({ id }) => {
          setConversations((prev) =>
            prev.map((c) => {
              if (c.id !== conversationId) return c;
              return {
                ...c,
                messages: c.messages.map((m) => (m.id === tempId ? { ...m, id } : m)),
              };
            })
          );
        })
        .catch(() => {});
      return tempId;
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
      // Fire-and-forget streaming update; server applies the same delta.
      updateMessageAction(conversationId, messageId, chunk, replace).catch(() => {});
    },
    []
  );

  const deleteConversation = useCallback((id: string) => {
    setConversations((prev) => {
      const target = prev.find((c) => c.id === id);
      if (target) {
        const blobIds = target.messages.flatMap((m) => m.attachments?.map((a) => a.id) ?? []);
        if (blobIds.length > 0) deleteBlobs(blobIds).catch(() => {});
      }
      return prev.filter((c) => c.id !== id);
    });
    deleteConversationAction(id).catch(() => {});
  }, []);

  const renameConversation = useCallback((id: string, title: string) => {
    if (!title) return;
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...c, title, updatedAt: Date.now() } : c))
    );
    renameConversationAction(id, title).catch(() => {});
  }, []);

  const setConversationModel = useCallback(
    (id: string, provider: Conversation['provider'], model: string) => {
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? { ...c, provider, model, updatedAt: Date.now() } : c))
      );
      setConversationModelAction(id, provider, model).catch(() => {});
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
    let cancelled = false;
    listUsageAction()
      .then((rows) => {
        if (cancelled) return;
        setUsageLog(rows);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    const savedWindow = localStorage.getItem(USAGE_WINDOW_KEY);
    if (savedWindow && USAGE_WINDOWS.some((w) => w.id === savedWindow)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setWindowState(savedWindow as UsageWindow);
    }
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!loaded) return;
    localStorage.setItem(USAGE_WINDOW_KEY, window);
  }, [window, loaded]);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);

  const recordUsage = useCallback((entry: Omit<UsageEntry, 'timestamp'>) => {
    const ts = Date.now();
    setUsageLog((prev) => [...prev, { ...entry, timestamp: ts }]);
    recordUsageAction(entry).catch(() => {});
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

export function useSettings() {
  const [settings, setSettingsState] = useState<Settings>(DEFAULT_SETTINGS);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getSettingsAction()
      .then((s) => {
        if (cancelled) return;
        setSettingsState(s);
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
    updateSettingsAction(next).catch(() => {});
  }, []);

  return { settings, setSettings, loaded };
}
