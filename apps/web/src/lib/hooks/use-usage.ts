'use client';

import { useEffect, useState } from 'react';
import { UsageEntry } from '@/lib/types';
import { PricingMap } from '@/lib/pricing';
import { usage as usageApi } from '@/lib/api';

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

/** The usage dashboard's data: every recorded LLM round (the server is the only writer —
 *  the automation executor and the builder assistant record them) plus current pricing. */
export function useUsage() {
  const pricing = usePricing();
  const [usageLog, setUsageLog] = useState<UsageEntry[]>([]);
  const [loaded, setLoaded] = useState(false);

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
    return () => {
      cancelled = true;
    };
  }, []);

  return { usageLog, pricing, loaded };
}
