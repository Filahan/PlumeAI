import 'server-only';
import { SignJWT, jwtVerify } from 'jose';
import { cookies } from 'next/headers';

const COOKIE_NAME = 'plumeai_session';
const ALG = 'HS256';
const SESSION_LIFETIME_S = 30 * 24 * 60 * 60; // 30 days

function getSecret(): Uint8Array {
  const raw = process.env.AUTH_SECRET;
  if (!raw) throw new Error('AUTH_SECRET is required');
  return new TextEncoder().encode(raw);
}

export async function createSession(): Promise<string> {
  const token = await new SignJWT({})
    .setProtectedHeader({ alg: ALG })
    .setIssuedAt()
    .setSubject('admin')
    .setExpirationTime(`${SESSION_LIFETIME_S}s`)
    .sign(getSecret());
  return token;
}

export async function verifySession(token: string | undefined): Promise<boolean> {
  if (!token) return false;
  try {
    await jwtVerify(token, getSecret(), { algorithms: [ALG] });
    return true;
  } catch {
    return false;
  }
}

export async function getSessionToken(): Promise<string | undefined> {
  const store = await cookies();
  return store.get(COOKIE_NAME)?.value;
}

export async function hasSession(): Promise<boolean> {
  const token = await getSessionToken();
  return verifySession(token);
}

export async function requireSession(): Promise<void> {
  if (!(await hasSession())) {
    throw new Error('Unauthorized');
  }
}

export { COOKIE_NAME as SESSION_COOKIE };
