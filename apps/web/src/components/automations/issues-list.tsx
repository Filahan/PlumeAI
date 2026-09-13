'use client';

import { AlertCircle } from 'lucide-react';
import type { ValidationIssue } from '@/lib/automations/types';

/** Validation issues as returned by the API: errors in red, warnings in amber, each
 *  prefixed by the document path it points at. */
export default function IssuesList({
  issues,
  className = '',
}: {
  issues: ValidationIssue[];
  className?: string;
}) {
  if (issues.length === 0) return null;
  return (
    <ul className={`space-y-1 ${className}`}>
      {issues.map((issue, i) => (
        <li
          key={`${issue.path}-${i}`}
          className={`text-[12px] flex items-start gap-1.5 ${
            issue.level === 'error' ? 'text-[#D4183D]' : 'text-[#b45309]'
          }`}
        >
          <AlertCircle size={12} strokeWidth={2} className="mt-0.5 shrink-0" />
          <span>
            <code className="text-[11px] opacity-70">{issue.path}</code> {issue.message}
          </span>
        </li>
      ))}
    </ul>
  );
}
