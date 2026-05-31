/** Next.js edge middleware — cookie presence check + login routing.
 *
 *  We don't verify the JWT signature here (no shared secret in the edge runtime by design).
 *  Every API request goes through nginx → FastAPI where the JWT is properly validated. This
 *  middleware only handles the page-level routing: redirect to /login when there's no
 *  session cookie at all, redirect away from /login when there is one.
 */

import { NextRequest, NextResponse } from 'next/server';

const COOKIE_NAME = 'plumeai_session';

export function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const hasCookie = !!req.cookies.get(COOKIE_NAME)?.value;

  // /login: render the form when no cookie, bounce to ?next or / when authed.
  if (pathname === '/login') {
    if (!hasCookie) return NextResponse.next();
    const next = req.nextUrl.searchParams.get('next');
    const dest = next && next.startsWith('/') && !next.startsWith('/login') ? next : '/';
    return NextResponse.redirect(new URL(dest, req.url));
  }

  // /api/* is the FastAPI backend (proxied by nginx) — it handles its own auth.
  if (pathname.startsWith('/api/')) return NextResponse.next();

  if (!hasCookie) {
    const url = new URL('/login', req.url);
    if (pathname && pathname !== '/') url.searchParams.set('next', pathname);
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
