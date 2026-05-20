'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import AppShell from '@/components/app-shell';
import UsageChart, { type UsageRange } from '@/components/usage-chart';
import { useUsageStore, useConversationsStore } from '@/lib/store-provider';
import { getCost, formatTokens, formatCost } from '@/lib/pricing';
import { ProviderLogo, PROVIDER_ACCENT } from '@/components/provider-logo';
import { PROVIDER_NAMES, Provider, UsageEntry } from '@/lib/types';
import { ArrowLeft, Coins, DollarSign, Zap, Layers } from 'lucide-react';

const RANGE_KEY = 'webui-usage-range';
const RANGES: { id: UsageRange; label: string }[] = [
  { id: '7d', label: '7d' },
  { id: '14d', label: '14d' },
  { id: '30d', label: '30d' },
  { id: 'all', label: 'All' },
];

function rangeCutoff(range: UsageRange): number {
  if (range === '7d') return Date.now() - 7 * 24 * 60 * 60 * 1000;
  if (range === '14d') return Date.now() - 14 * 24 * 60 * 60 * 1000;
  if (range === '30d') return Date.now() - 30 * 24 * 60 * 60 * 1000;
  return -Infinity;
}

interface ModelSummary {
  model: string;
  provider: Provider;
  calls: number;
  tokens: number;
  cost: number;
}

export default function UsagePage() {
  const { conversations } = useConversationsStore();
  const { usageLog, pricing, loaded } = useUsageStore();
  const [range, setRange] = useState<UsageRange>('7d');

  useEffect(() => {
    const saved = localStorage.getItem(RANGE_KEY);
    if (saved && RANGES.some((r) => r.id === saved)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setRange(saved as UsageRange);
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(RANGE_KEY, range);
  }, [range]);

  const filtered: UsageEntry[] = useMemo(() => {
    const cutoff = rangeCutoff(range);
    return usageLog.filter((e) => e.timestamp >= cutoff);
  }, [usageLog, range]);

  const stats = useMemo(() => {
    let totalTokens = 0;
    let totalCost = 0;
    const seenConvs = new Set<string>();
    const modelMap = new Map<string, ModelSummary>();
    for (const e of filtered) {
      const tokens = e.inputTokens + e.outputTokens;
      const cost = getCost(pricing, e.model, e.inputTokens, e.outputTokens);
      totalTokens += tokens;
      totalCost += cost;
      seenConvs.add(e.conversationId);
      const existing = modelMap.get(e.model);
      if (existing) {
        existing.calls += 1;
        existing.tokens += tokens;
        existing.cost += cost;
      } else {
        modelMap.set(e.model, { model: e.model, provider: e.provider, calls: 1, tokens, cost });
      }
    }
    const models = Array.from(modelMap.values()).sort((a, b) => b.tokens - a.tokens);
    return { totalTokens, totalCost, calls: filtered.length, models, conversations: seenConvs.size };
  }, [filtered, pricing]);

  const conversationCount = conversations.length;

  return (
    <AppShell currentId={null}>
      <div className="w-full max-w-[1100px] mx-auto px-6 py-8">
        {/* Header */}
        <div className="flex items-center justify-between gap-4 mb-6">
          <div className="flex items-center gap-3">
            <Link
              href="/"
              aria-label="Back"
              className="w-9 h-9 rounded-lg flex items-center justify-center text-[#5a5a5a] hover:bg-[#EEEEEE] hover:text-[#1c1c1c] transition-colors"
            >
              <ArrowLeft size={18} strokeWidth={2} />
            </Link>
            <div>
              <h1 className="text-[20px] font-semibold tracking-tight text-[#1c1c1c]">Usage</h1>
              <p className="text-[11px] text-[#8e8e8e]">Tokens and cost across your conversations.</p>
            </div>
          </div>

          {/* Range pills */}
          <div className="flex items-center gap-0.5 p-0.5 rounded-lg bg-black/[0.04]">
            {RANGES.map((r) => {
              const active = r.id === range;
              return (
                <button
                  key={r.id}
                  type="button"
                  onClick={() => setRange(r.id)}
                  aria-pressed={active}
                  className={`px-2.5 py-1 rounded-md text-[11px] font-medium tabular-nums transition-colors ${
                    active
                      ? 'bg-white text-[#1c1c1c] shadow-[0_1px_2px_rgba(0,0,0,0.06)]'
                      : 'text-[#8e8e8e] hover:text-[#1c1c1c]'
                  }`}
                >
                  {r.label}
                </button>
              );
            })}
          </div>
        </div>

        {!loaded ? (
          <div className="h-[400px]" />
        ) : filtered.length === 0 ? (
          <div className="rounded-2xl border border-black/[0.06] bg-[#FAFAFA] px-6 py-20 text-center">
            <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-white border border-black/[0.06] mb-4">
              <Zap size={20} strokeWidth={1.75} className="text-[#8e8e8e]" />
            </div>
            <h2 className="text-[16px] font-semibold text-[#1c1c1c] mb-1">No usage yet</h2>
            <p className="text-[13px] text-[#8e8e8e] mb-5">
              Start a conversation to see your token consumption broken down here.
            </p>
            <Link
              href="/"
              className="inline-flex items-center gap-2 h-10 px-4 rounded-full bg-[#1c1c1c] text-white text-[13px] font-medium hover:bg-[#333] transition-colors"
            >
              Back to chat
            </Link>
          </div>
        ) : (
          <>
            {/* Stat cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
              <StatCard icon={<Coins size={16} strokeWidth={2} />} label="Tokens" value={formatTokens(stats.totalTokens)} accent="#1c1c1c" />
              <StatCard icon={<DollarSign size={16} strokeWidth={2} />} label="Cost" value={formatCost(stats.totalCost)} accent="#047857" />
              <StatCard icon={<Zap size={16} strokeWidth={2} />} label="Calls" value={stats.calls.toString()} accent="#1c1c1c" />
              <StatCard icon={<Layers size={16} strokeWidth={2} />} label="Models" value={stats.models.length.toString()} subtitle={`${conversationCount} conversation${conversationCount === 1 ? '' : 's'}`} accent="#1c1c1c" />
            </div>

            {/* Chart card */}
            <div className="rounded-2xl border border-black/[0.06] bg-white p-5 mb-6">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h2 className="text-[14px] font-semibold text-[#1c1c1c]">Tokens per day</h2>
                  <p className="text-[11px] text-[#8e8e8e]">Stacked by model.</p>
                </div>
              </div>
              <UsageChart entries={filtered} pricing={pricing} range={range} />
            </div>

            {/* Per-model breakdown */}
            <div className="rounded-2xl border border-black/[0.06] bg-white overflow-hidden">
              <div className="px-5 pt-4 pb-2">
                <h2 className="text-[14px] font-semibold text-[#1c1c1c]">By model</h2>
                <p className="text-[11px] text-[#8e8e8e]">Sorted by token usage.</p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  <thead>
                    <tr className="text-left text-[11px] font-medium text-[#8e8e8e] uppercase tracking-[0.06em] border-b border-black/[0.06]">
                      <th className="px-5 py-2.5 font-medium">Model</th>
                      <th className="px-5 py-2.5 font-medium text-right">Calls</th>
                      <th className="px-5 py-2.5 font-medium text-right">Tokens</th>
                      <th className="px-5 py-2.5 font-medium text-right">Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.models.map((m) => (
                      <tr key={`${m.provider}:${m.model}`} className="border-b border-black/[0.04] last:border-0 hover:bg-[#FAFAFA] transition-colors">
                        <td className="px-5 py-3">
                          <div className="flex items-center gap-2.5 min-w-0">
                            <div className={`w-7 h-7 rounded-md bg-[#FAFAFA] border border-black/[0.06] flex items-center justify-center shrink-0 ${PROVIDER_ACCENT[m.provider]}`}>
                              <ProviderLogo provider={m.provider} size={14} />
                            </div>
                            <div className="min-w-0">
                              <div className="text-[13px] text-[#1c1c1c] truncate font-mono">{m.model}</div>
                              <div className="text-[11px] text-[#8e8e8e]">{PROVIDER_NAMES[m.provider]}</div>
                            </div>
                          </div>
                        </td>
                        <td className="px-5 py-3 text-right tabular-nums text-[#1c1c1c]">{m.calls}</td>
                        <td className="px-5 py-3 text-right tabular-nums text-[#1c1c1c]">{formatTokens(m.tokens)}</td>
                        <td className="px-5 py-3 text-right tabular-nums text-emerald-700 font-medium">{formatCost(m.cost)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}

function StatCard({ icon, label, value, subtitle, accent }: { icon: React.ReactNode; label: string; value: string; subtitle?: string; accent: string }) {
  return (
    <div className="rounded-2xl border border-black/[0.06] bg-white p-4">
      <div className="flex items-center gap-1.5 text-[#8e8e8e] mb-2">
        {icon}
        <span className="text-[11px] font-medium uppercase tracking-[0.06em]">{label}</span>
      </div>
      <div className="text-[20px] font-semibold tracking-tight tabular-nums" style={{ color: accent }}>{value}</div>
      {subtitle && <div className="text-[11px] text-[#8e8e8e] mt-0.5">{subtitle}</div>}
    </div>
  );
}
