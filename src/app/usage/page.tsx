'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import AppShell from '@/components/app-shell';
import UsageChart, { type UsageRange } from '@/components/usage-chart';
import { useUsageStore, useConversationsStore } from '@/lib/store-provider';
import { getCost, formatTokens, formatCost } from '@/lib/pricing';
import { ProviderLogo } from '@/components/provider-logo';
import { PROVIDER_NAMES, PROVIDER_ACCENT, Provider, UsageEntry } from '@/lib/types';
import { Coins, DollarSign, Zap, Layers } from 'lucide-react';

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
  const router = useRouter();
  const { conversations, deleteConversation } = useConversationsStore();
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
    <AppShell
      currentId={null}
      onSelect={(id) => router.push(`/${id}`)}
      onNewChat={() => router.push('/')}
      onDelete={(id) => deleteConversation(id)}
    >
      <div className="w-full max-w-[1100px] mx-auto px-8 py-8 overflow-y-auto h-full">
        {/* Header */}
        <div className="flex items-center justify-between gap-4 mb-6">
          <div>
            <h1 className="text-[20px] font-semibold tracking-tight">Usage</h1>
            <p className="text-[11px] text-[color:var(--muted-foreground)]">Tokens and cost across your conversations.</p>
          </div>

          {/* Range pills */}
          <div className="flex items-center gap-0.5 p-0.5 rounded-lg bg-[color:var(--surface-muted)]">
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
                      ? 'bg-white text-[color:var(--foreground)] shadow-[0_1px_2px_rgba(0,0,0,0.06)]'
                      : 'text-[color:var(--muted-foreground)] hover:text-[color:var(--foreground)]'
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
          <div className="rounded-2xl border border-[color:var(--border)] bg-[color:var(--surface-muted)] px-6 py-20 text-center">
            <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-white border border-[color:var(--border)] mb-4">
              <Zap size={20} strokeWidth={1.75} className="text-[color:var(--muted-foreground)]" />
            </div>
            <h2 className="text-[16px] font-semibold mb-1">No usage yet</h2>
            <p className="text-[13px] text-[color:var(--muted-foreground)] mb-5">
              Start a conversation to see your token consumption broken down here.
            </p>
            <Link
              href="/"
              className="inline-flex items-center gap-2 h-10 px-4 rounded-full bg-[color:var(--primary)] text-white text-[13px] font-medium hover:opacity-90 transition"
            >
              Back to chat
            </Link>
          </div>
        ) : (
          <>
            {/* Stat cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
              <StatCard icon={<Coins size={16} strokeWidth={2} />} label="Tokens" value={formatTokens(stats.totalTokens)} />
              <StatCard icon={<DollarSign size={16} strokeWidth={2} />} label="Cost" value={formatCost(stats.totalCost)} accent="text-emerald-700" />
              <StatCard icon={<Zap size={16} strokeWidth={2} />} label="Calls" value={stats.calls.toString()} />
              <StatCard icon={<Layers size={16} strokeWidth={2} />} label="Models" value={stats.models.length.toString()} subtitle={`${conversationCount} conversation${conversationCount === 1 ? '' : 's'}`} />
            </div>

            {/* Chart card */}
            <div className="rounded-2xl border border-[color:var(--border)] bg-white p-5 mb-6">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h2 className="text-[14px] font-semibold">Tokens per day</h2>
                  <p className="text-[11px] text-[color:var(--muted-foreground)]">Stacked by model.</p>
                </div>
              </div>
              <UsageChart entries={filtered} pricing={pricing} range={range} />
            </div>

            {/* Per-model breakdown */}
            <div className="rounded-2xl border border-[color:var(--border)] bg-white overflow-hidden">
              <div className="px-5 pt-4 pb-2">
                <h2 className="text-[14px] font-semibold">By model</h2>
                <p className="text-[11px] text-[color:var(--muted-foreground)]">Sorted by token usage.</p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  <thead>
                    <tr className="text-left text-[11px] font-medium text-[color:var(--muted-foreground)] uppercase tracking-[0.06em] border-b border-[color:var(--border)]">
                      <th className="px-5 py-2.5 font-medium">Model</th>
                      <th className="px-5 py-2.5 font-medium text-right">Calls</th>
                      <th className="px-5 py-2.5 font-medium text-right">Tokens</th>
                      <th className="px-5 py-2.5 font-medium text-right">Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.models.map((m) => (
                      <tr key={`${m.provider}:${m.model}`} className="border-b border-[color:var(--border)] last:border-0 hover:bg-[color:var(--surface-muted)] transition-colors">
                        <td className="px-5 py-3">
                          <div className="flex items-center gap-2.5 min-w-0">
                            <div className={`w-7 h-7 rounded-md bg-[color:var(--surface-muted)] border border-[color:var(--border)] flex items-center justify-center shrink-0 ${PROVIDER_ACCENT[m.provider]}`}>
                              <ProviderLogo provider={m.provider} size={14} />
                            </div>
                            <div className="min-w-0">
                              <div className="text-[13px] truncate font-mono">{m.model}</div>
                              <div className="text-[11px] text-[color:var(--muted-foreground)]">{PROVIDER_NAMES[m.provider]}</div>
                            </div>
                          </div>
                        </td>
                        <td className="px-5 py-3 text-right tabular-nums">{m.calls}</td>
                        <td className="px-5 py-3 text-right tabular-nums">{formatTokens(m.tokens)}</td>
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

function StatCard({ icon, label, value, subtitle, accent }: { icon: React.ReactNode; label: string; value: string; subtitle?: string; accent?: string }) {
  return (
    <div className="rounded-2xl border border-[color:var(--border)] bg-white p-4">
      <div className="flex items-center gap-1.5 text-[color:var(--muted-foreground)] mb-2">
        {icon}
        <span className="text-[11px] font-medium uppercase tracking-[0.06em]">{label}</span>
      </div>
      <div className={`text-[22px] font-semibold tracking-tight tabular-nums ${accent ?? ''}`}>{value}</div>
      {subtitle && <div className="text-[11px] text-[color:var(--muted-foreground)] mt-0.5">{subtitle}</div>}
    </div>
  );
}
