import 'server-only';

import dns from 'node:dns/promises';
import net from 'node:net';

const TIMEOUT_MS = 20_000;
const MAX_RESULT_CHARS = 12_000;
const USER_AGENT =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) PlumeAI-Automations/1.0';

/* ───────────────── Built-in tool schemas (OpenAI function-calling format) ───────────────── */

export const BUILTIN_TOOL_SCHEMAS = [
  {
    type: 'function',
    function: {
      name: 'web_search',
      description: 'Search the web and return the top results (title, url, snippet). Use when you do not have a URL.',
      parameters: {
        type: 'object',
        properties: { query: { type: 'string', description: 'Search query.' } },
        required: ['query'],
        additionalProperties: false,
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'web_fetch',
      description: 'Fetch a single web page and return its readable text content. Use to read a known URL (e.g. a product page).',
      parameters: {
        type: 'object',
        properties: { url: { type: 'string', description: 'Absolute http(s) URL to fetch.' } },
        required: ['url'],
        additionalProperties: false,
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'http',
      description:
        'Send an HTTP request to an API endpoint and return the response body as text. Use for JSON APIs and any non-GET method.',
      parameters: {
        type: 'object',
        properties: {
          method: { type: 'string', enum: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'], description: 'HTTP method.' },
          url: { type: 'string', description: 'Absolute http(s) URL.' },
          body: { type: 'string', description: 'Request body (string; for JSON, pass a JSON-encoded string).' },
          headers: {
            type: 'object',
            description: 'Extra request headers as a flat key/value object.',
            additionalProperties: { type: 'string' },
          },
        },
        required: ['method', 'url'],
        additionalProperties: false,
      },
    },
  },
] as const;

export const BUILTIN_TOOL_NAMES = new Set(['web_search', 'web_fetch', 'http']);

export type ToolResult = { ok: boolean; content: string };

/* ───────────────── SSRF guard ───────────────── */

function isPrivateIPv4(ip: string): boolean {
  const p = ip.split('.').map(Number);
  if (p.length !== 4 || p.some((n) => Number.isNaN(n))) return true;
  const [a, b] = p;
  if (a === 10 || a === 127 || a === 0) return true;
  if (a === 169 && b === 254) return true;
  if (a === 172 && b >= 16 && b <= 31) return true;
  if (a === 192 && b === 168) return true;
  if (a === 100 && b >= 64 && b <= 127) return true;
  return false;
}

function isPrivateIPv6(ip: string): boolean {
  const v = ip.toLowerCase();
  if (v === '::1' || v === '::') return true;
  if (v.startsWith('fc') || v.startsWith('fd') || v.startsWith('fe80')) return true;
  const mapped = v.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/);
  if (mapped) return isPrivateIPv4(mapped[1]);
  return false;
}

function isPrivateAddr(ip: string): boolean {
  return net.isIPv6(ip) ? isPrivateIPv6(ip) : isPrivateIPv4(ip);
}

async function assertPublicUrl(raw: string): Promise<URL> {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`Invalid URL: ${raw}`);
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new Error(`Only http(s) URLs are allowed (got ${url.protocol}).`);
  }
  const host = url.hostname.replace(/^\[|\]$/g, '');
  if (host === 'localhost' || host.endsWith('.local') || host.endsWith('.internal')) {
    throw new Error('Requests to internal hosts are not allowed.');
  }
  if (net.isIP(host)) {
    if (isPrivateAddr(host)) throw new Error('Requests to private addresses are not allowed.');
    return url;
  }
  const addrs = await dns.lookup(host, { all: true }).catch(() => {
    throw new Error(`Could not resolve host: ${host}`);
  });
  if (addrs.some((a) => isPrivateAddr(a.address))) {
    throw new Error('Host resolves to a private address; blocked.');
  }
  return url;
}

/* ───────────────── helpers ───────────────── */

function cap(text: string): string {
  return text.length > MAX_RESULT_CHARS ? text.slice(0, MAX_RESULT_CHARS) + '\n…[truncated]' : text;
}

function decodeEntities(s: string): string {
  return s
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;|&#39;/g, "'");
}

function stripTags(s: string): string {
  return decodeEntities(s.replace(/<[^>]+>/g, '')).replace(/\s+/g, ' ').trim();
}

function htmlToText(html: string): string {
  return decodeEntities(
    html
      .replace(/<script[\s\S]*?<\/script>/gi, ' ')
      .replace(/<style[\s\S]*?<\/style>/gi, ' ')
      .replace(/<!--[\s\S]*?-->/g, ' ')
      .replace(/<[^>]+>/g, ' ')
  )
    .replace(/[ \t]+/g, ' ')
    .replace(/\n\s*\n\s*\n+/g, '\n\n')
    .trim();
}

function withTimeout(parent: AbortSignal): { signal: AbortSignal; clear: () => void } {
  const ctrl = new AbortController();
  const onAbort = () => ctrl.abort();
  parent.addEventListener('abort', onAbort, { once: true });
  const timer = setTimeout(() => ctrl.abort(new Error('Tool timeout')), TIMEOUT_MS);
  return {
    signal: ctrl.signal,
    clear: () => {
      clearTimeout(timer);
      parent.removeEventListener('abort', onAbort);
    },
  };
}

/* ───────────────── web_search (DuckDuckGo, zero-config) ───────────────── */

function decodeDuckDuckGoUrl(href: string): string {
  const m = href.match(/[?&]uddg=([^&]+)/);
  if (m) {
    try {
      return decodeURIComponent(m[1]);
    } catch {
      return href;
    }
  }
  return href.startsWith('//') ? 'https:' + href : href;
}

function parseDuckDuckGo(html: string): { title: string; url: string; snippet: string }[] {
  const links: { title: string; url: string }[] = [];
  const linkRe = /<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/g;
  let m: RegExpExecArray | null;
  while ((m = linkRe.exec(html))) links.push({ url: decodeDuckDuckGoUrl(m[1]), title: stripTags(m[2]) });

  const snippets: string[] = [];
  const snipRe = /<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>([\s\S]*?)<\/a>/g;
  while ((m = snipRe.exec(html))) snippets.push(stripTags(m[1]));

  return links.map((l, i) => ({ ...l, snippet: snippets[i] ?? '' }));
}

async function webSearch(args: { query?: unknown }, parent: AbortSignal): Promise<ToolResult> {
  if (typeof args.query !== 'string' || !args.query.trim()) {
    return { ok: false, content: 'web_search requires a non-empty "query" string.' };
  }
  const t = withTimeout(parent);
  try {
    const res = await fetch(`https://html.duckduckgo.com/html/?q=${encodeURIComponent(args.query)}`, {
      headers: { 'User-Agent': USER_AGENT, Accept: 'text/html' },
      signal: t.signal,
    });
    if (!res.ok) return { ok: false, content: `Search failed: HTTP ${res.status}` };
    const results = parseDuckDuckGo(await res.text()).slice(0, 5);
    if (results.length === 0) return { ok: true, content: 'No results found.' };
    const text = results.map((r, i) => `${i + 1}. ${r.title}\n   ${r.url}\n   ${r.snippet}`).join('\n\n');
    return { ok: true, content: cap(text) };
  } finally {
    t.clear();
  }
}

/* ───────────────── web_fetch ───────────────── */

async function webFetch(args: { url?: unknown }, parent: AbortSignal): Promise<ToolResult> {
  if (typeof args.url !== 'string') return { ok: false, content: 'web_fetch requires a "url" string.' };
  const url = await assertPublicUrl(args.url);
  const t = withTimeout(parent);
  try {
    const res = await fetch(url, { headers: { 'User-Agent': USER_AGENT, Accept: 'text/html,*/*' }, signal: t.signal });
    const ctype = res.headers.get('content-type') ?? '';
    const raw = await res.text();
    const text = ctype.includes('html') ? htmlToText(raw) : raw;
    return { ok: res.ok, content: cap(`HTTP ${res.status} ${url.href}\n\n${text}`) };
  } finally {
    t.clear();
  }
}

/* ───────────────── http (arbitrary method) ───────────────── */

const ALLOWED_METHODS = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE']);

async function httpRequest(
  args: { method?: unknown; url?: unknown; body?: unknown; headers?: unknown },
  parent: AbortSignal
): Promise<ToolResult> {
  const method = typeof args.method === 'string' ? args.method.toUpperCase() : 'GET';
  if (!ALLOWED_METHODS.has(method)) return { ok: false, content: `Unsupported method: ${method}` };
  if (typeof args.url !== 'string') return { ok: false, content: 'http requires a "url" string.' };
  const url = await assertPublicUrl(args.url);

  const headers: Record<string, string> = { 'User-Agent': USER_AGENT, Accept: '*/*' };
  if (args.headers && typeof args.headers === 'object') {
    for (const [k, v] of Object.entries(args.headers as Record<string, unknown>)) {
      if (typeof v === 'string') headers[k] = v;
    }
  }
  const body = method === 'GET' || method === 'DELETE' || args.body == null ? undefined : String(args.body);

  const t = withTimeout(parent);
  try {
    const res = await fetch(url, { method, headers, body, signal: t.signal });
    const ctype = res.headers.get('content-type') ?? '';
    const raw = await res.text();
    const text = ctype.includes('html') ? htmlToText(raw) : raw;
    return { ok: res.ok, content: cap(`HTTP ${res.status} ${method} ${url.href}\n\n${text}`) };
  } finally {
    t.clear();
  }
}

/* ───────────────── dispatch ───────────────── */

export async function executeBuiltinTool(name: string, rawArgs: string, signal: AbortSignal): Promise<ToolResult> {
  let args: Record<string, unknown>;
  try {
    args = rawArgs ? (JSON.parse(rawArgs) as Record<string, unknown>) : {};
  } catch {
    return { ok: false, content: `Invalid JSON arguments for ${name}.` };
  }
  try {
    if (name === 'web_search') return await webSearch(args, signal);
    if (name === 'web_fetch') return await webFetch(args, signal);
    if (name === 'http') return await httpRequest(args, signal);
    return { ok: false, content: `Unknown built-in tool: ${name}` };
  } catch (e) {
    const message = e instanceof Error ? e.message : 'Tool execution failed';
    return { ok: false, content: `Error: ${message}` };
  }
}

/** Truncate args for safe display in the transcript/SSE. */
export function redactArgs(rawArgs: string): string {
  return rawArgs.length > 600 ? rawArgs.slice(0, 600) + '…' : rawArgs;
}

/** Unified tool dispatcher: built-in tools go through the if-chain above, anything else is routed
 *  to the tool registry by function name (e.g. `gmail_send` → gmailTool.execute). */
export async function executeTool(name: string, rawArgs: string, signal: AbortSignal): Promise<ToolResult> {
  if (BUILTIN_TOOL_NAMES.has(name)) return executeBuiltinTool(name, rawArgs, signal);
  const { findToolForFunction } = await import('@/lib/tools/registry');
  const tool = findToolForFunction(name);
  if (!tool) return { ok: false, content: `Unknown tool: ${name}` };
  let args: Record<string, unknown>;
  try {
    args = rawArgs ? (JSON.parse(rawArgs) as Record<string, unknown>) : {};
  } catch {
    return { ok: false, content: `Invalid JSON arguments for ${name}.` };
  }
  return tool.execute(name, args, signal);
}
