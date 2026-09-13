'use client';

import { useState } from 'react';
import { Plug, Server } from 'lucide-react';

/** The 32px tile at the head of a row. Some catalog logos 404 (the CDN doesn't have every
 *  brand), so a failed load unmounts the `<img>` entirely — a broken-image glyph in a
 *  32px tile reads as a bug, the lucide fallback reads as "no logo". */
export default function ToolLogo({
  src,
  fallback,
}: {
  src?: string | null;
  fallback: 'integration' | 'mcp';
}) {
  const [failed, setFailed] = useState(false);
  const Icon = fallback === 'mcp' ? Server : Plug;

  return (
    <span className="w-8 h-8 rounded-[9px] border border-[color:var(--border)] bg-[color:var(--surface-muted)] flex items-center justify-center shrink-0 overflow-hidden">
      {src && !failed ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt=""
          aria-hidden="true"
          className="w-4 h-4 object-contain"
          onError={() => setFailed(true)}
        />
      ) : (
        <Icon
          size={15}
          strokeWidth={1.75}
          aria-hidden="true"
          className="text-[color:var(--muted-foreground)]"
        />
      )}
    </span>
  );
}
