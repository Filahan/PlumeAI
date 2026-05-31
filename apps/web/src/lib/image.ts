export const MAX_IMAGES_PER_MESSAGE = 8;
const MAX_DIMENSION = 2048;
const MAX_SIZE_BYTES = 10 * 1024 * 1024;

const SUPPORTED_MIME = new Set(['image/jpeg', 'image/png', 'image/webp', 'image/gif']);

interface ProcessedImage {
  blob: Blob;
  mime: string;
  width: number;
  height: number;
  size: number;
}

export async function processImage(file: File): Promise<ProcessedImage> {
  if (!SUPPORTED_MIME.has(file.type)) {
    throw new Error(`Unsupported image type: ${file.type || 'unknown'}`);
  }

  const bitmap = await createImageBitmap(file);
  const { width: srcW, height: srcH } = bitmap;
  const longest = Math.max(srcW, srcH);

  let blob: Blob;
  let outW = srcW;
  let outH = srcH;
  let outMime = file.type;

  // GIFs can be animated — preserve them as-is rather than flattening on canvas.
  if (file.type === 'image/gif') {
    blob = file;
  } else if (longest <= MAX_DIMENSION && file.size <= 2 * 1024 * 1024) {
    // Small enough to send untouched.
    blob = file;
  } else {
    const scale = longest > MAX_DIMENSION ? MAX_DIMENSION / longest : 1;
    outW = Math.round(srcW * scale);
    outH = Math.round(srcH * scale);

    const canvas: OffscreenCanvas | HTMLCanvasElement =
      typeof OffscreenCanvas !== 'undefined'
        ? new OffscreenCanvas(outW, outH)
        : Object.assign(document.createElement('canvas'), { width: outW, height: outH });
    const ctx = (canvas as HTMLCanvasElement).getContext('2d');
    if (!ctx) throw new Error('Could not get 2D context');
    ctx.drawImage(bitmap, 0, 0, outW, outH);

    // Keep PNG if the source was PNG (preserves alpha). JPEG otherwise for size.
    outMime = file.type === 'image/png' ? 'image/png' : 'image/jpeg';
    const quality = outMime === 'image/jpeg' ? 0.9 : undefined;

    if (canvas instanceof OffscreenCanvas) {
      blob = await canvas.convertToBlob({ type: outMime, quality });
    } else {
      blob = await new Promise<Blob>((resolve, reject) => {
        canvas.toBlob(
          (b) => (b ? resolve(b) : reject(new Error('toBlob returned null'))),
          outMime,
          quality
        );
      });
    }
  }

  bitmap.close?.();

  if (blob.size > MAX_SIZE_BYTES) {
    throw new Error(`Image too large: ${Math.round(blob.size / 1024 / 1024)} MB (max ${MAX_SIZE_BYTES / 1024 / 1024} MB)`);
  }

  return { blob, mime: outMime, width: outW, height: outH, size: blob.size };
}

export async function blobToBase64(blob: Blob): Promise<string> {
  const buf = await blob.arrayBuffer();
  const bytes = new Uint8Array(buf);
  // Chunked to avoid call-stack overflow on very large arrays.
  let binary = '';
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + CHUNK)) as number[]);
  }
  return btoa(binary);
}
