'use client';

import { useMemo } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { UsageEntry } from '@/lib/types';
import { PricingMap, getCost, formatTokens, formatCost } from '@/lib/pricing';

export type UsageRange = '7d' | '14d' | '30d' | 'all';

interface UsageChartProps {
  entries: UsageEntry[];
  pricing: PricingMap;
  range: UsageRange;
}

const PALETTE = [
  '#10A37F', // OpenAI teal
  '#D97706', // Anthropic orange
  '#6366f1', // OpenRouter indigo
  '#0EA5E9',
  '#EC4899',
  '#F59E0B',
  '#8B5CF6',
  '#22C55E',
];

function colorFor(_model: string, index: number): string {
  return PALETTE[index % PALETTE.length];
}

function startOfDay(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

function dayKey(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function rangeDays(range: UsageRange): number | null {
  if (range === '7d') return 7;
  if (range === '14d') return 14;
  if (range === '30d') return 30;
  return null;
}

function buildBuckets(entries: UsageEntry[], range: UsageRange) {
  const now = new Date();
  const days = rangeDays(range);

  // Determine the day axis. For fixed ranges we fill every day so the chart
  // shows a continuous timeline even when there's no activity on some days.
  let axis: Date[];
  if (days !== null) {
    axis = [];
    const start = startOfDay(new Date(now.getTime() - (days - 1) * 24 * 60 * 60 * 1000));
    for (let i = 0; i < days; i++) {
      axis.push(new Date(start.getTime() + i * 24 * 60 * 60 * 1000));
    }
  } else {
    // 'all' — earliest entry to today
    if (entries.length === 0) {
      axis = [startOfDay(now)];
    } else {
      const earliest = entries.reduce(
        (min, e) => (e.timestamp < min ? e.timestamp : min),
        entries[0].timestamp
      );
      const start = startOfDay(new Date(earliest));
      const dayMs = 24 * 60 * 60 * 1000;
      const count = Math.max(1, Math.round((startOfDay(now).getTime() - start.getTime()) / dayMs) + 1);
      axis = [];
      for (let i = 0; i < count; i++) axis.push(new Date(start.getTime() + i * dayMs));
    }
  }

  const cutoff = days !== null ? axis[0].getTime() : -Infinity;
  const filtered = entries.filter((e) => e.timestamp >= cutoff);

  const models = Array.from(new Set(filtered.map((e) => e.model))).sort();
  const modelIndex = new Map(models.map((m, i) => [m, i]));

  type Row = { day: string; label: string; [model: string]: string | number };
  const rows: Row[] = axis.map((d) => {
    const row: Row = { day: dayKey(d), label: d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) };
    for (const m of models) row[m] = 0;
    return row;
  });

  const rowIndex = new Map(rows.map((r, i) => [r.day, i]));
  for (const e of filtered) {
    const k = dayKey(new Date(e.timestamp));
    const i = rowIndex.get(k);
    if (i === undefined) continue;
    rows[i][e.model] = (rows[i][e.model] as number) + e.inputTokens + e.outputTokens;
  }

  return { rows, models, modelIndex };
}

interface TooltipPayloadItem {
  dataKey: string;
  value: number;
  color: string;
}

function ChartTooltip({
  active, payload, label, pricing,
}: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string;
  pricing: PricingMap;
}) {
  if (!active || !payload || payload.length === 0) return null;
  // payload's `payload` carries the row; we just use payload[].dataKey and value.
  const total = payload.reduce((s, p) => s + (p.value ?? 0), 0);
  if (total === 0) return null;
  // Approximate cost using getCost — we don't track in/out split per day, so call it as input-only.
  // Cost shown is a best-effort estimate from the total tokens since we don't keep the in/out split per row.
  let estCost = 0;
  for (const p of payload) {
    // Use average split — best-effort estimate
    const tokens = p.value as number;
    if (!tokens) continue;
    estCost += getCost(pricing, p.dataKey, tokens / 2, tokens / 2);
  }

  return (
    <div className="rounded-xl bg-white border border-black/[0.08] shadow-lg px-3 py-2.5 text-[12px]">
      <div className="text-[#1c1c1c] font-medium mb-1.5">{label}</div>
      <div className="space-y-1">
        {payload
          .filter((p) => p.value && p.value > 0)
          .map((p) => (
            <div key={p.dataKey} className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-1.5 min-w-0">
                <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: p.color }} />
                <span className="text-[#5a5a5a] truncate font-mono">{p.dataKey}</span>
              </div>
              <span className="text-[#1c1c1c] tabular-nums">{formatTokens(p.value as number)}</span>
            </div>
          ))}
      </div>
      <div className="mt-2 pt-2 border-t border-black/[0.06] flex items-center justify-between gap-4">
        <span className="text-[#8e8e8e]">Total</span>
        <div className="flex items-baseline gap-2">
          <span className="text-[#1c1c1c] tabular-nums">{formatTokens(total)} tok</span>
          <span className="text-emerald-700 tabular-nums font-medium">{formatCost(estCost)}</span>
        </div>
      </div>
    </div>
  );
}

export default function UsageChart({ entries, pricing, range }: UsageChartProps) {
  const { rows, models } = useMemo(() => buildBuckets(entries, range), [entries, range]);

  if (rows.length === 0) {
    return <div className="text-[14px] text-[#8e8e8e] text-center py-10">No usage data.</div>;
  }

  return (
    <div className="w-full h-[340px]">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 16, right: 8, left: 0, bottom: 0 }} barCategoryGap="22%">
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.06)" vertical={false} />
          <XAxis
            dataKey="label"
            stroke="#9b9b9b"
            tick={{ fontSize: 12 }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            stroke="#9b9b9b"
            tick={{ fontSize: 12 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => formatTokens(v)}
            width={48}
          />
          <Tooltip
            cursor={{ fill: 'rgba(0,0,0,0.03)' }}
            content={(props) => (
              <ChartTooltip
                active={props.active}
                payload={(props.payload as unknown as TooltipPayloadItem[] | undefined) ?? undefined}
                label={typeof props.label === 'string' ? props.label : undefined}
                pricing={pricing}
              />
            )}
          />
          <Legend
            verticalAlign="top"
            height={32}
            iconType="circle"
            iconSize={8}
            wrapperStyle={{ fontSize: 12, color: '#5a5a5a' }}
          />
          {models.map((m, i) => (
            <Bar
              key={m}
              dataKey={m}
              stackId="tokens"
              fill={colorFor(m, i)}
              radius={i === models.length - 1 ? [6, 6, 0, 0] : 0}
              isAnimationActive={false}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
