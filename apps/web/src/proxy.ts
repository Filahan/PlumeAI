import { NextRequest, NextResponse } from 'next/server';
import { jwtVerify } from 'jose';
import { db } from '@/lib/db';
import { settings } from '@/lib/db/schema';
import { eq } from 'drizzle-orm';

const COOKIE_NAME = 'plumeai_session';

async function isAuthed(token: string | undefined): Promise<boolean> {
  const secret = process.env.AUTH_SECRET;
  if (!token || !secret) return false;
  try {
    await jwtVerify(token, new TextEncoder().encode(secret), { algorithms: ['HS256'] });
    return true;
  } catch {
    return false;
  }
}

async function hasProvider(): Promise<boolean> {
  const [row] = await db
    .select({ providers: settings.providers })
    .from(settings)
    .where(eq(settings.id, 1));
  return !!row?.providers.some((p) => p.apiKeyCiphertext?.length);
}

function redirect(req: NextRequest, path: string, next?: string) {
  const url = new URL(path, req.url);
  if (next) url.searchParams.set('next', next);
  return NextResponse.redirect(url);
}

export async function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const authed = await isAuthed(req.cookies.get(COOKIE_NAME)?.value);

  // /login: let the form render when unauthenticated; bounce to ?next or / when authed.
  if (pathname === '/login') {
    if (!authed) return NextResponse.next();
    const next = req.nextUrl.searchParams.get('next');
    const dest = next && next.startsWith('/') && !next.startsWith('/login') ? next : '/';
    return NextResponse.redirect(new URL(dest, req.url));
  }

  // Public endpoints — no session required.
  if (pathname === '/api/auth/login' || pathname === '/api/health') {
    return NextResponse.next();
  }

  // Everything else requires a session.
  if (!authed) return redirect(req, '/login', pathname);

  // Force /setup until a provider key is configured; bounce away once it is.
  if (pathname === '/' || pathname === '/setup') {
    const configured = await hasProvider();
    if (!configured && pathname === '/') return redirect(req, '/setup');
    if (configured && pathname === '/setup') return redirect(req, '/');
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
