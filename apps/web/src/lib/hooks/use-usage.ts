'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { UsageEntry } from '@/lib/types';
import { getCost, PricingMap } from '@/lib/pricing';
import { usage as usageApi } from '@/lib/api';

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
        /* corrupt — fall through */
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

export function useUsage() {
  const pricing = usePricing();
  const [usageLog, setUsageLog] = useState<UsageEntry[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [window, setWindowState] = useState<UsageWindow>('30m');

  useEffect(() => {
    let cancelled = false;
    usageApi
      .list()
      .then((rows) => {
        if (!cancelled) setUsageLog(rows);
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
    // Persist optimistically in local log; FastAPI already recorded server-side.
    const ts = Date.now();
    setUsageLog((prev) => [...prev, { ...entry, timestamp: ts }]);
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

  return { recordUsage, recentUsage, window, setWindow, usageLog, pricing, loaded };
}
