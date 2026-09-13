"""Built-in tools available to every agent run: web_search, web_fetch, http.

These three are universally available regardless of which integrations the user has
connected — they handle the "search the web / fetch a URL / call an arbitrary API" needs.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx
import structlog

from app.errors import ToolError
from app.integrations.base import ActionMeta, describe_action
from app.tools.base import (
    TIMEOUT_SECONDS,
    USER_AGENT,
    ToolResult,
    assert_public_url,
    cap,
    with_timeout,
)

log = structlog.get_logger("app.tools.builtin")

ALLOWED_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

# OpenAI function-calling schemas. The agent runner injects these into the LLM request.
BUILTIN_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web and return the top results (title, url, snippet). "
                "Use when you do not have a URL."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search query."}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "Fetch a single web page and return its readable text content. "
                "Use to read a known URL (e.g. a product page)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "Absolute http(s) URL."}},
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "http",
            "description": (
                "Send an HTTP request to an API endpoint and return the response body as "
                "text. Use for JSON APIs and any non-GET method."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "enum": list(ALLOWED_HTTP_METHODS),
                        "description": "HTTP method.",
                    },
                    "url": {"type": "string", "description": "Absolute http(s) URL."},
                    "body": {
                        "type": "string",
                        "description": "Request body (string; for JSON, pass a JSON-encoded string).",
                    },
                    "headers": {
                        "type": "object",
                        "description": "Extra request headers as a flat key/value object.",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["method", "url"],
                "additionalProperties": False,
            },
        },
    },
]

BUILTIN_NAMES = {s["function"]["name"] for s in BUILTIN_SCHEMAS}

# Human-facing metadata for the catalog (`GET /tools`). Keyed by function name.
BUILTIN_ACTION_META: dict[str, ActionMeta] = {
    "web_search": ActionMeta(
        label="Search the web",
        output_description="Top results with title, url, and snippet.",
    ),
    "web_fetch": ActionMeta(
        label="Fetch a web page",
        output_description="Readable text content of the page.",
    ),
    "http": ActionMeta(
        label="HTTP request",
        output_description="Response status code and body text.",
    ),
}


def describe_builtin_actions() -> list[dict[str, Any]]:
    """Catalog-ready descriptors for the built-in tools, integration="builtin"."""
    return [describe_action(s, "builtin", BUILTIN_ACTION_META) for s in BUILTIN_SCHEMAS]


# ───────────────────── tiny HTML helpers ─────────────────────

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<script[\s\S]*?</script>", re.IGNORECASE)
_STYLE_RE = re.compile(r"<style[\s\S]*?</style>", re.IGNORECASE)
_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
_WS_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n\s*\n\s*\n+")


def _decode_entities(s: str) -> str:
    return (
        s.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#x27;", "'")
        .replace("&#39;", "'")
    )


def html_to_text(html: str) -> str:
    s = _SCRIPT_RE.sub(" ", html)
    s = _STYLE_RE.sub(" ", s)
    s = _COMMENT_RE.sub(" ", s)
    s = _TAG_RE.sub(" ", s)
    s = _decode_entities(s)
    s = _WS_RE.sub(" ", s)
    s = _BLANK_LINES_RE.sub("\n\n", s)
    return s.strip()


# ───────────────────── web_search (DuckDuckGo HTML, zero-config) ─────────────────────

_DDG_LINK_RE = re.compile(
    r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>'
)
_DDG_SNIPPET_RE = re.compile(
    r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>([\s\S]*?)</a>'
)


def _strip_tags(s: str) -> str:
    return _decode_entities(_TAG_RE.sub("", s)).strip()


def _decode_ddg_url(href: str) -> str:
    m = re.search(r"[?&]uddg=([^&]+)", href)
    if m:
        from urllib.parse import unquote

        try:
            return unquote(m.group(1))
        except Exception:  # noqa: BLE001
            return href
    return ("https:" + href) if href.startswith("//") else href


async def web_search(args: dict[str, Any]) -> ToolResult:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return ToolResult(ok=False, content='web_search requires a non-empty "query" string.')

    url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
            r = await with_timeout(
                client.get(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
            )
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, content=f"Search failed: {exc}")
    if not r.is_success:
        return ToolResult(ok=False, content=f"Search failed: HTTP {r.status_code}")

    html = r.text
    links = [(_decode_ddg_url(m.group(1)), _strip_tags(m.group(2))) for m in _DDG_LINK_RE.finditer(html)]
    snippets = [_strip_tags(m.group(1)) for m in _DDG_SNIPPET_RE.finditer(html)]
    results = [(u, t, snippets[i] if i < len(snippets) else "") for i, (u, t) in enumerate(links[:5])]
    if not results:
        return ToolResult(ok=True, content="No results found.")
    text = "\n\n".join(f"{i + 1}. {t}\n   {u}\n   {s}" for i, (u, t, s) in enumerate(results))
    return ToolResult(ok=True, content=cap(text))


# ───────────────────── web_fetch ─────────────────────

async def web_fetch(args: dict[str, Any]) -> ToolResult:
    url_raw = args.get("url")
    if not isinstance(url_raw, str):
        return ToolResult(ok=False, content='web_fetch requires a "url" string.')
    url = await assert_public_url(url_raw)
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
        r = await with_timeout(
            client.get(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"})
        )
    ctype = r.headers.get("content-type", "")
    raw = r.text
    text = html_to_text(raw) if "html" in ctype else raw
    return ToolResult(ok=r.is_success, content=cap(f"HTTP {r.status_code} {url}\n\n{text}"))


# ───────────────────── http (arbitrary method) ─────────────────────

async def http_request(args: dict[str, Any]) -> ToolResult:
    method = (args.get("method") or "GET").upper()
    if method not in ALLOWED_HTTP_METHODS:
        return ToolResult(ok=False, content=f"Unsupported method: {method}")
    url_raw = args.get("url")
    if not isinstance(url_raw, str):
        return ToolResult(ok=False, content='http requires a "url" string.')
    url = await assert_public_url(url_raw)

    headers: dict[str, str] = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    extra = args.get("headers")
    if isinstance(extra, dict):
        for k, v in extra.items():
            if isinstance(v, str):
                headers[k] = v
    body = None
    if method not in {"GET", "DELETE"} and args.get("body") is not None:
        body = str(args["body"])

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
        r = await with_timeout(
            client.request(method=method, url=url, headers=headers, content=body)
        )
    ctype = r.headers.get("content-type", "")
    raw = r.text
    text = html_to_text(raw) if "html" in ctype else raw
    return ToolResult(
        ok=r.is_success,
        content=cap(f"HTTP {r.status_code} {method} {url}\n\n{text}"),
    )


BUILTIN_DISPATCH = {
    "web_search": web_search,
    "web_fetch": web_fetch,
    "http": http_request,
}
