import { NextRequest, NextResponse } from 'next/server';
import { requireSession } from '@/lib/auth';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const STATE_COOKIE = 'gmail_oauth_state';

function toolsRedirect(req: NextRequest, status: 'connected' | 'error', message?: string): NextResponse {
  const url = new URL('/tools', req.url);
  url.searchParams.set('tool', 'gmail');
  url.searchParams.set('status', status);
  if (message) url.searchParams.set('message', message);
  const res = NextResponse.redirect(url);
  res.cookies.delete(STATE_COOKIE);
  return res;
}

export async function GET(req: NextRequest) {
  try {
    await requireSession();
  } catch {
    return new Response('Unauthorized', { status: 401 });
  }

  const { exchangeCode, saveCreds } = await import('@/lib/tools/gmail/oauth');
  const { ensureMigrations } = await import('@/lib/db');
  await ensureMigrations();

  const params = req.nextUrl.searchParams;
  const error = params.get('error');
  if (error) return toolsRedirect(req, 'error', error);

  const code = params.get('code');
  const state = params.get('state');
  const expected = req.cookies.get(STATE_COOKIE)?.value;
  if (!code || !state || !expected || state !== expected) {
    return toolsRedirect(req, 'error', 'invalid_state');
  }

  const origin = new URL(req.url).origin;
  const redirectUri = `${origin}/api/tools/gmail/oauth/callback`;

  try {
    const creds = await exchangeCode(code, redirectUri);
    await saveCreds(creds);
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Token exchange failed.';
    return toolsRedirect(req, 'error', msg);
  }

  return toolsRedirect(req, 'connected');
}
