/** Typed fetch client for the FastAPI backend.
 *
 *  All endpoints sit behind the nginx reverse proxy at `/api/*`. There is no login —
 *  the app is single-user and trusts whoever can reach it — so just call these functions.
 */

const BASE = '/api';

export class ApiError extends Error {
  status: number;
  detail?: string;
  requestId?: string;
  problem?: Record<string, unknown>;

  constructor(status: number, problem: Record<string, unknown>) {
    const detail = typeof problem.detail === 'string' ? problem.detail : '';
    const title = typeof problem.title === 'string' ? problem.title : 'Request failed';
    super(detail || title);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.requestId = typeof problem.request_id === 'string' ? problem.request_id : undefined;
    this.problem = problem;
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (res.ok) {
    // No-content endpoints (e.g. DELETE) — return undefined cast as T.
    if (res.status === 204 || res.headers.get('content-length') === '0') {
      return undefined as T;
    }
    return (await res.json()) as T;
  }
  let body: Record<string, unknown> = {};
  try {
    body = await res.json();
  } catch {
    /* non-JSON error — leave body empty */
  }
  throw new ApiError(res.status, body);
}

export const api = {
  async get<T>(path: string): Promise<T> {
    return handle<T>(await fetch(`${BASE}${path}`, { credentials: 'same-origin' }));
  },
  async post<T>(path: string, body?: unknown): Promise<T> {
    return handle<T>(
      await fetch(`${BASE}${path}`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: body === undefined ? undefined : { 'content-type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      })
    );
  },
  async put<T>(path: string, body: unknown): Promise<T> {
    return handle<T>(
      await fetch(`${BASE}${path}`, {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
    );
  },
  async patch<T>(path: string, body: unknown): Promise<T> {
    return handle<T>(
      await fetch(`${BASE}${path}`, {
        method: 'PATCH',
        credentials: 'same-origin',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
    );
  },
  async delete<T = void>(path: string): Promise<T> {
    return handle<T>(
      await fetch(`${BASE}${path}`, { method: 'DELETE', credentials: 'same-origin' })
    );
  },
  /** SSE helper — returns the raw Response so callers can iterate `body.getReader()`. */
  async sse(path: string, body: unknown, signal?: AbortSignal): Promise<Response> {
    const res = await fetch(`${BASE}${path}`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    });
    if (!res.ok || !res.body) {
      const problem = await res.json().catch(() => ({}));
      throw new ApiError(res.status, problem);
    }
    return res;
  },
};
