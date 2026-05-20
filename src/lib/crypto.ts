import 'server-only';

const ALGO = 'AES-GCM';
const IV_BYTES = 12;

function base64ToBuffer(b64: string): ArrayBuffer {
  const bin = Buffer.from(b64, 'base64');
  // Copy into a fresh ArrayBuffer to satisfy strict BufferSource types.
  const out = new ArrayBuffer(bin.length);
  new Uint8Array(out).set(bin);
  return out;
}

function bytesToBase64(bytes: ArrayBuffer | Uint8Array): string {
  return Buffer.from(bytes as ArrayBuffer).toString('base64');
}

let cachedKey: CryptoKey | null = null;

async function getKey(): Promise<CryptoKey> {
  if (cachedKey) return cachedKey;
  const raw = process.env.ENCRYPTION_KEY;
  if (!raw) throw new Error('ENCRYPTION_KEY is required');
  const buf = base64ToBuffer(raw);
  if (buf.byteLength !== 32) {
    throw new Error(`ENCRYPTION_KEY must decode to 32 bytes (got ${buf.byteLength})`);
  }
  cachedKey = await crypto.subtle.importKey('raw', buf, ALGO, false, ['encrypt', 'decrypt']);
  return cachedKey;
}

export async function encrypt(plaintext: string): Promise<{ iv: string; ct: string }> {
  const key = await getKey();
  const ivBuf = new ArrayBuffer(IV_BYTES);
  crypto.getRandomValues(new Uint8Array(ivBuf));
  const data = new TextEncoder().encode(plaintext);
  const dataBuf = new ArrayBuffer(data.length);
  new Uint8Array(dataBuf).set(data);
  const ct = await crypto.subtle.encrypt({ name: ALGO, iv: ivBuf }, key, dataBuf);
  return { iv: bytesToBase64(ivBuf), ct: bytesToBase64(ct) };
}

export async function decrypt(iv: string, ct: string): Promise<string> {
  const key = await getKey();
  const plain = await crypto.subtle.decrypt(
    { name: ALGO, iv: base64ToBuffer(iv) },
    key,
    base64ToBuffer(ct)
  );
  return new TextDecoder().decode(plain);
}

export async function sha256Hex(input: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input));
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

export function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}
