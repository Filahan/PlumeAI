'use client';

import { useEffect, useState } from 'react';
import { AttachmentRef } from '@/lib/types';
import { getBlob } from '@/lib/blob-store';

interface ImageThumbProps {
  attachment: AttachmentRef;
  size?: number;
  rounded?: string;
  onClick?: () => void;
}

export default function ImageThumb({ attachment, size = 80, rounded = 'rounded-xl', onClick }: ImageThumbProps) {
  const [url, setUrl] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let createdUrl: string | null = null;
    (async () => {
      try {
        const blob = await getBlob(attachment.id);
        if (cancelled) return;
        if (!blob) {
          setMissing(true);
          return;
        }
        createdUrl = URL.createObjectURL(blob);
        setUrl(createdUrl);
      } catch {
        if (!cancelled) setMissing(true);
      }
    })();
    return () => {
      cancelled = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [attachment.id]);

  const style = { width: size, height: size };

  if (missing) {
    return (
      <div
        style={style}
        className={`${rounded} bg-[#F4F4F4] flex items-center justify-center text-[10px] text-[#9b9b9b] border border-dashed border-black/[0.08]`}
      >
        missing
      </div>
    );
  }

  if (!url) {
    return <div style={style} className={`${rounded} bg-[#F4F4F4] animate-pulse`} />;
  }

  return (
    <button
      type="button"
      onClick={onClick}
      style={style}
      className={`${rounded} overflow-hidden bg-[#F4F4F4] border border-black/[0.05] hover:border-black/[0.15] transition relative group`}
      aria-label="View image"
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={url} alt="" className="w-full h-full object-cover" />
    </button>
  );
}
