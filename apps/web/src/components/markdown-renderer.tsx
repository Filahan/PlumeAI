'use client';

import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

const components: Components = {
  a: ({ children, ...props }) => (
    <a {...props} target="_blank" rel="noopener noreferrer" className="text-[color:var(--foreground)] underline underline-offset-2 decoration-[color:var(--muted-foreground)] hover:decoration-[color:var(--foreground)]">
      {children}
    </a>
  ),
  code: ({ className, children, ...props }) => {
    const isBlock = /language-/.test(className || '');
    if (isBlock) {
      return (
        <code className={className} {...props}>
          {children}
        </code>
      );
    }
    return (
      <code
        className="bg-white border border-[color:var(--border)] rounded px-1 py-0.5 text-[0.9em] font-mono"
        {...props}
      >
        {children}
      </code>
    );
  },
  pre: ({ children, ...props }) => (
    <pre
      className="bg-[#1A1A1F] text-[#F2F2F5] rounded-lg p-4 overflow-x-auto text-[12px] leading-relaxed my-3"
      {...props}
    >
      {children}
    </pre>
  ),
  table: ({ children, ...props }) => (
    <div className="overflow-x-auto my-3">
      <table className="border-collapse text-[13px]" {...props}>
        {children}
      </table>
    </div>
  ),
  th: ({ children, ...props }) => (
    <th className="border border-[color:var(--border)] bg-[color:var(--surface-muted)] px-3 py-1.5 text-left font-semibold" {...props}>
      {children}
    </th>
  ),
  td: ({ children, ...props }) => (
    <td className="border border-[color:var(--border)] px-3 py-1.5" {...props}>
      {children}
    </td>
  ),
};

export function MarkdownRenderer({ content }: { content: string }) {
  return (
    <div className="prose prose-stone max-w-none text-[14px] leading-relaxed">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
