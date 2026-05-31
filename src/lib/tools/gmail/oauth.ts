import 'server-only';

import { eq } from 'drizzle-orm';
import { db } from '@/lib/db';
import { settings } from '@/lib/db/schema';
import { encrypt, decrypt } from '@/lib/crypto';

export const GMAIL_SCOPES = [
  'https://www.googleapis.com/auth/gmail.modify',  // read + modify labels + trash + mark read
  'https://www.googleapis.com/auth/gmail.send',
  'https://www.googleapis.com/auth/gmail.labels',
].join(' ');

const AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth';
const TOKEN_URL = 'https://oauth2.googleapis.com/token';
const TOOL_KEY = 'gmail';

export interface GmailCreds {
  accessToken: string;
  refreshToken: string;
  /** Unix ms when accessToken expires. */
  expiresAt: number;
  scope: string;
  tokenType: string;
}

function requireEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`${name} is required (set it in your .env to enable Gmail).`);
  return v;
}

export function buildAuthUrl(state: string, redirectUri: string): string {
  const params = new URLSearchParams({
    client_id: requireEnv('GOOGLE_OAUTH_CLIENT_ID'),
    redirect_uri: redirectUri,
    response_type: 'code',
    scope: GMAIL_SCOPES,
    access_type: 'offline',
    prompt: 'consent',  // force refresh_token issuance even if previously granted
    include_granted_scopes: 'true',
    state,
  });
  return `${AUTH_URL}?${params.toString()}`;
}

interface TokenResponse {
  access_token: string;
  refresh_token?: string;
  expires_in: number;
  scope: string;
  token_type: string;
}

async function postToken(body: URLSearchParams): Promise<TokenResponse> {
  const res = await fetch(TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });
  const json = (await res.json()) as TokenResponse & { error?: string; error_description?: string };
  if (!res.ok) {
    throw new Error(json.error_description || json.error || `Token endpoint error: ${res.status}`);
  }
  return json;
}

export async function exchangeCode(code: string, redirectUri: string): Promise<GmailCreds> {
  const tokens = await postToken(
    new URLSearchParams({
      code,
      client_id: requireEnv('GOOGLE_OAUTH_CLIENT_ID'),
      client_secret: requireEnv('GOOGLE_OAUTH_CLIENT_SECRET'),
      redirect_uri: redirectUri,
      grant_type: 'authorization_code',
    })
  );
  if (!tokens.refresh_token) {
    throw new Error('Google did not return a refresh_token. Revoke the app in your Google account and try again.');
  }
  return {
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token,
    expiresAt: Date.now() + (tokens.expires_in - 60) * 1000,  // 60s safety margin
    scope: tokens.scope,
    tokenType: tokens.token_type,
  };
}

async function refreshAccessToken(refreshToken: string): Promise<Pick<GmailCreds, 'accessToken' | 'expiresAt' | 'tokenType'>> {
  const tokens = await postToken(
    new URLSearchParams({
      client_id: requireEnv('GOOGLE_OAUTH_CLIENT_ID'),
      client_secret: requireEnv('GOOGLE_OAUTH_CLIENT_SECRET'),
      refresh_token: refreshToken,
      grant_type: 'refresh_token',
    })
  );
  return {
    accessToken: tokens.access_token,
    expiresAt: Date.now() + (tokens.expires_in - 60) * 1000,
    tokenType: tokens.token_type,
  };
}

export async function loadCreds(): Promise<GmailCreds | null> {
  const [row] = await db.select().from(settings).where(eq(settings.id, 1));
  const blob = row?.tools?.[TOOL_KEY];
  if (!blob?.ciphertext || !blob.iv) return null;
  try {
    return JSON.parse(await decrypt(blob.iv, blob.ciphertext)) as GmailCreds;
  } catch {
    return null;
  }
}

export async function saveCreds(creds: GmailCreds): Promise<void> {
  const { iv, ct } = await encrypt(JSON.stringify(creds));
  const [row] = await db.select().from(settings).where(eq(settings.id, 1));
  const nextTools = { ...(row?.tools ?? {}), [TOOL_KEY]: { ciphertext: ct, iv } };
  await db.update(settings).set({ tools: nextTools }).where(eq(settings.id, 1));
}

/** Return a valid access token. Refreshes if expired and persists the new token. */
export async function getValidAccessToken(): Promise<string> {
  const creds = await loadCreds();
  if (!creds) throw new Error('Gmail is not connected.');
  if (Date.now() < creds.expiresAt) return creds.accessToken;

  const refreshed = await refreshAccessToken(creds.refreshToken);
  const next: GmailCreds = { ...creds, ...refreshed };
  await saveCreds(next);
  return next.accessToken;
}
