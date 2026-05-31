import 'server-only';

import { getValidAccessToken, loadCreds, saveCreds } from '@/lib/tools/gmail/oauth';

const GMAIL_BASE = 'https://gmail.googleapis.com/gmail/v1';
const TIMEOUT_MS = 20_000;

/** Authed fetch against the Gmail API. On 401, force a token refresh and retry once. */
export async function gmailFetch(
  path: string,
  init: RequestInit = {},
  parentSignal?: AbortSignal
): Promise<Response> {
  const ctrl = new AbortController();
  const onAbort = () => ctrl.abort();
  parentSignal?.addEventListener('abort', onAbort, { once: true });
  const timer = setTimeout(() => ctrl.abort(new Error('Gmail request timeout')), TIMEOUT_MS);

  try {
    const url = path.startsWith('http') ? path : `${GMAIL_BASE}${path}`;
    const headers = new Headers(init.headers);
    headers.set('Authorization', `Bearer ${await getValidAccessToken()}`);
    if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');

    let res = await fetch(url, { ...init, headers, signal: ctrl.signal });
    if (res.status !== 401) return res;

    // Token might have been revoked or rotated under us — force a refresh by zeroing expiresAt
    // and retrying. If still 401, surface the response as-is.
    const creds = await loadCreds();
    if (!creds) return res;
    await saveCreds({ ...creds, expiresAt: 0 });
    headers.set('Authorization', `Bearer ${await getValidAccessToken()}`);
    res = await fetch(url, { ...init, headers, signal: ctrl.signal });
    return res;
  } finally {
    clearTimeout(timer);
    parentSignal?.removeEventListener('abort', onAbort);
  }
}
