import { NextRequest, NextResponse } from 'next/server';
import { requireSession } from '@/lib/auth';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const STATE_COOKIE = 'gmail_oauth_state';

function randomState(): string {
  return Buffer.from(crypto.getRandomValues(new Uint8Array(24))).toString('base64url');
}

export async function GET(req: NextRequest) {
  try {
    await requireSession();
  } catch {
    return new Response('Unauthorized', { status: 401 });
  }

  const { buildAuthUrl } = await import('@/lib/tools/gmail/oauth');

  const state = randomState();
  const origin = new URL(req.url).origin;
  const redirectUri = `${origin}/api/tools/gmail/oauth/callback`;

  let authUrl: string;
  try {
    authUrl = buildAuthUrl(state, redirectUri);
  } catch (e) {
    const msg = e instanceof Error ? e.message : '';
    // Friendly path when the server is missing the Google OAuth credentials: bounce the user
    // back to /tools with a flag that triggers an inline setup guide instead of a raw 500.
    if (/GOOGLE_OAUTH_CLIENT_(ID|SECRET)/.test(msg)) {
      const url = new URL('/tools', req.url);
      url.searchParams.set('gmail_setup', 'required');
      return NextResponse.redirect(url);
    }
    return new Response(msg || 'Could not start OAuth.', { status: 500 });
  }

  const res = NextResponse.redirect(authUrl);
  res.cookies.set(STATE_COOKIE, state, {
    httpOnly: true,
    sameSite: 'lax',
    secure: req.nextUrl.protocol === 'https:',
    path: '/',
    maxAge: 600,  // 10 minutes
  });
  return res;
}
