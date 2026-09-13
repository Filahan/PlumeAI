/** Reading an `ApiError` the way the editor needs it: one sentence for a banner, the
 *  server's own wording behind a disclosure, and the two very different kinds of
 *  per-field problem a rejected write can carry. */

import { ApiError } from '@/lib/api';
import type { ValidationIssue } from './types';

export function errorMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError) return e.message || fallback;
  if (e instanceof Error) return e.message || fallback;
  return fallback;
}

/** The server's raw wording, kept out of the banner itself — a Pydantic `detail` is
 *  often several lines long. */
export function errorDetail(e: unknown): string | null {
  if (e instanceof ApiError) return e.detail || e.message || null;
  if (e instanceof Error) return e.message || null;
  return null;
}

/** HTTP status, when the failure came from the API at all. Lets a caller tell apart
 *  failures that read alike (a missing API key is a 404, a provider outage a 502). */
export function errorStatus(e: unknown): number | null {
  return e instanceof ApiError ? e.status : null;
}

/** Issues a rejected write raised **about the document** — the `extra.issues` of a 422
 *  from `PUT /automations/{id}`, already in the shape `IssuesList` renders. Only these
 *  may replace `current.issues`. */
export function documentIssuesFromError(e: unknown): ValidationIssue[] | null {
  if (!(e instanceof ApiError)) return null;
  const extra = e.problem?.extra as { issues?: unknown } | undefined;
  if (!Array.isArray(extra?.issues) || extra.issues.length === 0) return null;
  return extra.issues as ValidationIssue[];
}

/** Issues a rejected write raised **about the request** — FastAPI's `errors[]`, whose
 *  paths point into the payload (`operations.0.set_trigger`) and say nothing about the
 *  document. They belong to the banner, not to `current.issues`. */
export function requestIssuesFromError(e: unknown): ValidationIssue[] {
  if (!(e instanceof ApiError)) return [];
  return documentIssuesFromError(e) ? [] : e.issues;
}
