'use client';

import { useEffect, useState } from 'react';
import { AttachmentRef } from '@/lib/types';
import { getBlob } from '@/lib/blob-store';
import { X } from 'lucide-react';

interface ImageLightboxProps {
  attachment: AttachmentRef | null;
  onClose: () => void;
}

export default function ImageLightbox({ attachment, onClose }: ImageLightboxProps) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!attachment) return;
    let cancelled = false;
    let createdUrl: string | null = null;
    (async () => {
      const blob = await getBlob(attachment.id);
      if (cancelled || !blob) return;
      createdUrl = URL.createObjectURL(blob);
      setUrl(createdUrl);
    })();
    return () => {
      cancelled = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
      setUrl(null);
    };
  }, [attachment]);

  useEffect(() => {
    if (!attachment) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [attachment, onClose]);

  if (!attachment) return null;

  return (
    <div
      className="fixed inset-0 z-[60] bg-black/80 backdrop-blur-sm flex items-center justify-center p-6 animate-in fade-in-0 duration-150"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <button
        type="button"
        onClick={onClose}
        aria-label="Close"
        className="absolute top-4 right-4 w-10 h-10 rounded-full bg-white/10 hover:bg-white/20 text-white flex items-center justify-center transition-colors"
      >
        <X size={20} strokeWidth={2} />
      </button>
      {url && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={url}
          alt=""
          className="max-h-full max-w-full object-contain rounded-lg"
          onClick={(e) => e.stopPropagation()}
        />
      )}
    </div>
  );
}
