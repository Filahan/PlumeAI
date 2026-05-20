import { NextRequest, NextResponse } from 'next/server';
import { createSession, SESSION_COOKIE } from '@/lib/auth';
import { sha256Hex, timingSafeEqual } from '@/lib/crypto';

const SESSION_LIFETIME_S = 30 * 24 * 60 * 60;

export async function POST(req: NextRequest) {
  const expected = process.env.ADMIN_PASSWORD_HASH;
  if (!expected) {
    return NextResponse.json({ error: 'Server not configured' }, { status: 500 });
  }

  let password = '';
  try {
    const body = await req.json();
    if (typeof body?.password === 'string') password = body.password;
  } catch {
    // empty or invalid JSON
  }
  if (!password) {
    return NextResponse.json({ error: 'Password required' }, { status: 400 });
  }

  const got = await sha256Hex(password);
  if (!timingSafeEqual(got, expected.toLowerCase())) {
    return NextResponse.json({ error: 'Invalid password' }, { status: 401 });
  }

  const token = await createSession();
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, token, {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: SESSION_LIFETIME_S,
  });
  return res;
}
