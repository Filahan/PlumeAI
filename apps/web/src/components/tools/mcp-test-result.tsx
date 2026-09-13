'use client';

import { AlertCircle, Check } from 'lucide-react';
import type { McpTestResult } from '@/lib/automations/types';

/** The outcome of `POST /mcp/servers/test`, inline under the form: the tools that came
 *  back, or the reason nothing did. */
export default function McpTestResultPanel({ result }: { result: McpTestResult }) {
  if (!result.ok) {
    return (
      <p className="flex items-start gap-1.5 rounded-lg border border-[#D4183D]/30 bg-[#D4183D]/5 px-3 py-2 text-[12px] text-[#D4183D] leading-relaxed">
        <AlertCircle size={13} strokeWidth={2.25} className="mt-px shrink-0" />
        <span className="break-words">{result.error || "The server didn't answer."}</span>
      </p>
    );
  }

  return (
    <div className="rounded-lg border border-[#10A37F]/30 bg-[#10A37F]/5 px-3 py-2 text-[12px] text-[#0B7F63] leading-relaxed">
      <span className="inline-flex items-center gap-1.5 font-medium">
        <Check size={13} strokeWidth={2.5} /> Connected · {result.tools.length}{' '}
        {result.tools.length === 1 ? 'tool' : 'tools'}
      </span>
      {result.tools.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {result.tools.map((t) => (
            <span
              key={t.name}
              title={t.description || undefined}
              className="rounded-md bg-white/70 border border-[#10A37F]/20 px-1.5 py-px font-mono text-[10px]"
            >
              {t.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
