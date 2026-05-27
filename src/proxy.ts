import { NextRequest, NextResponse } from 'next/server';
import { jwtVerify } from 'jose';
import { db } from '@/lib/db';
import { settings } from '@/lib/db/schema';
import { eq } from 'drizzle-orm';

const COOKIE_NAME = 'plumeai_session';
const ALG = 'HS256';

const PUBLIC_PATHS = ['/login', '/api/auth/login', '/api/health'];

function getSecret(): Uint8Array {
  const raw = process.env.AUTH_SECRET;
  if (!raw) throw new Error('AUTH_SECRET is required');
  return new TextEncoder().encode(raw);
}

async function isSessionValid(token: string | undefined): Promise<boolean> {
  if (!token) return false;
  try {
    await jwtVerify(token, getSecret(), { algorithms: [ALG] });
    return true;
  } catch {
    return false;
  }
}

async function hasAnyProvider(): Promise<boolean> {
  const [row] = await db.select({ providers: settings.providers }).from(settings).where(eq(settings.id, 1));
  if (!row) return false;
  return row.providers.some((p) => p.apiKeyCiphertext && p.apiKeyCiphertext.length > 0);
}

export async function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;

  // Always allow public paths and Next.js internals (_next/* is excluded by matcher).
  if (PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(p + '/'))) {
    return NextResponse.next();
  }

  const token = req.cookies.get(COOKIE_NAME)?.value;
  if (!(await isSessionValid(token))) {
    const url = req.nextUrl.clone();
    url.pathname = '/login';
    url.searchParams.set('next', pathname);
    return NextResponse.redirect(url);
  }

  // Authenticated. Gate `/` and `/setup` on whether any provider is configured.
  if (pathname === '/' || pathname === '/setup') {
    const configured = await hasAnyProvider();
    if (!configured && pathname === '/') {
      const url = req.nextUrl.clone();
      url.pathname = '/setup';
      return NextResponse.redirect(url);
    }
    if (configured && pathname === '/setup') {
      const url = req.nextUrl.clone();
      url.pathname = '/';
      return NextResponse.redirect(url);
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
