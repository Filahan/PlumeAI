/** Typed fetch client for the FastAPI backend.
 *
 *  All endpoints sit behind the nginx reverse proxy at `/api/*`. There is no login —
 *  the app is single-user and trusts whoever can reach it — so just call these functions.
 */

import type { ValidationIssue } from '@/lib/automations/types';

const BASE = '/api';

/** One entry of FastAPI's `errors[]` (a `RequestValidationError` body). */
interface RequestError {
  loc?: unknown;
  msg?: unknown;
  type?: unknown;
}

/** `["body", "operations", 0, "add_step"]` → `"operations.0.add_step"`. The leading
 *  `body` is noise — every write we make puts its payload there. */
function issuePath(loc: unknown): string {
  if (!Array.isArray(loc)) return '';
  const parts = loc.map((part) => String(part));
  if (parts[0] === 'body') parts.shift();
  return parts.join('.');
}

/** The three error envelopes the API can answer a document write with, flattened into
 *  the one shape the editor renders (`IssuesList`):
 *
 *    - 422 from `PUT /automations/{id}` → `extra.issues`, already in this shape;
 *    - 422 from `POST .../operations`  → `errors[]` (`{loc, msg, type}`) plus a generic
 *      `detail`, so the useful part is the per-field list;
 *    - 400 from `POST .../operations`  → a human `detail` and nothing else, which stays
 *      in `ApiError.detail` and surfaces as the banner's “Details”.
 */
function normalizeIssues(problem: Record<string, unknown>): ValidationIssue[] {
  const extra = problem.extra as { issues?: unknown } | undefined;
  if (Array.isArray(extra?.issues)) return extra.issues as ValidationIssue[];

  const errors = problem.errors;
  if (!Array.isArray(errors)) return [];
  return errors.map((entry) => {
    const row = (entry ?? {}) as RequestError;
    return {
      path: issuePath(row.loc),
      message: typeof row.msg === 'string' ? row.msg : 'Invalid value',
      level: 'error' as const,
    };
  });
}

export class ApiError extends Error {
  status: number;
  detail?: string;
  requestId?: string;
  problem?: Record<string, unknown>;
  /** Per-field problems, normalized from whichever envelope the server used. */
  issues: ValidationIssue[];

  constructor(status: number, problem: Record<string, unknown>) {
    const detail = typeof problem.detail === 'string' ? problem.detail : '';
    const title = typeof problem.title === 'string' ? problem.title : 'Request failed';
    super(detail || title);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.requestId = typeof problem.request_id === 'string' ? problem.request_id : undefined;
    this.problem = problem;
    this.issues = normalizeIssues(problem);
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
  /** GET-based SSE helper (run event streams) — returns the raw Response so callers
   *  can iterate `body.getReader()`, or hand it to `parseSSE`. */
  async sseGet(path: string, signal?: AbortSignal): Promise<Response> {
    const res = await fetch(`${BASE}${path}`, {
      method: 'GET',
      credentials: 'same-origin',
      headers: { accept: 'text/event-stream' },
      signal,
    });
    if (!res.ok || !res.body) {
      const problem = await res.json().catch(() => ({}));
      throw new ApiError(res.status, problem);
    }
    return res;
  },
};
