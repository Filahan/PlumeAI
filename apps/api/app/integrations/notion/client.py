"""Notion API client: internal-integration-token auth, one `notion_call` entry point,
and the small readers that turn Notion's verbose JSON into plain values.

Kept separate from `tools.py` so the HTTP/error-mapping layer and the property readers
can be tested on their own.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ToolError, ToolNotConfigured
from app.services.tool_credentials import get_credentials
from app.tools.base import TIMEOUT_SECONDS, with_timeout

log = structlog.get_logger("app.integrations.notion")

NOTION_BASE = "https://api.notion.com"
NOTION_VERSION = "2022-06-28"
CREDENTIALS_NAMESPACE = "notion"

# A failure the automation executor should not retry — the request itself is wrong.
_PERMANENT = {"retryable": False}

_NOT_SHARED = (
    "Notion could not find that page or database (404). Either the id is wrong, or the "
    'page is not shared with the integration — open it in Notion, click "…" → '
    "Connections → your integration. If this id is a database, read it with "
    "notion_query_database (notion_get_page only reads pages)."
)


def _http_client() -> httpx.AsyncClient:
    """Factory for the HTTP client. Tests replace this to inject an `httpx.MockTransport`."""
    return httpx.AsyncClient(timeout=TIMEOUT_SECONDS)


async def notion_token(session: AsyncSession) -> str:
    creds = await get_credentials(session, CREDENTIALS_NAMESPACE)
    token = (creds or {}).get("token")
    if not token:
        raise ToolNotConfigured(
            "Notion is not configured. Open the Notion card in Settings → Tools and save "
            "your internal integration secret."
        )
    return str(token)


async def notion_call(
    session: AsyncSession,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call the Notion API and return the parsed body, mapping failures to `ToolError`.

    Notion uses real HTTP status codes (unlike Slack), so the mapping is per-status: a bad
    token or an unshared page will fail identically next time (non-retryable), while a 429
    or a 5xx is worth another attempt.
    """
    token = await notion_token(session)
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    async with _http_client() as client:
        r = await with_timeout(
            client.request(
                method=method,
                url=f"{NOTION_BASE}{path}",
                headers=headers,
                json=json_body,
                params=params,
            )
        )

    if r.is_success:
        try:
            payload = r.json()
        except ValueError as exc:
            raise ToolError("Notion returned a non-JSON response.") from exc
        return payload if isinstance(payload, dict) else {}

    message = _notion_message(r)
    if r.status_code == 401:
        raise ToolError(
            "Notion rejected the token (401). Re-copy the internal integration secret "
            "from notion.so/my-integrations into Settings → Tools → Notion.",
            extra=dict(_PERMANENT),
        )
    if r.status_code == 404:
        raise ToolError(_NOT_SHARED, extra=dict(_PERMANENT))
    if r.status_code == 429:
        retry_after = r.headers.get("retry-after", "30")
        raise ToolError(
            f"Notion rate-limited the request. Retry after {retry_after}s.",
            extra={"retry_after": _int_or_none(retry_after)},
        )
    if r.status_code == 403:
        raise ToolError(
            f"Notion refused the request (403). Check the integration's capabilities "
            f"(read/insert/update content). {message}",
            extra=dict(_PERMANENT),
        )
    if r.status_code == 400:
        raise ToolError(f"Notion rejected the request: {message}", extra=dict(_PERMANENT))
    log.info("notion_api_error", status=r.status_code, path=path)
    raise ToolError(f"Notion request failed: HTTP {r.status_code} {message}")


def _int_or_none(value: str) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _notion_message(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return r.text[:300]
    if isinstance(body, dict):
        return str(body.get("message") or body.get("code") or "")[:400]
    return r.text[:300]


# ─── readers: Notion JSON → plain Python values ──────────────────────────────────────


def rich_text_to_plain(rich: Any) -> str:
    """Join a Notion rich-text array into plain text."""
    if not isinstance(rich, list):
        return ""
    return "".join(
        str(item.get("plain_text") or "") for item in rich if isinstance(item, dict)
    ).strip()


def extract_title(obj: dict[str, Any]) -> str:
    """Title of a page (the one `title`-typed property) or a database (its `title` array)."""
    kind = obj.get("object")
    if kind == "database":
        title = rich_text_to_plain(obj.get("title"))
        if title:
            return title
    props = obj.get("properties")
    if isinstance(props, dict):
        for value in props.values():
            if isinstance(value, dict) and value.get("type") == "title":
                title = rich_text_to_plain(value.get("title"))
                if title:
                    return title
    # Data-source / inline-title fallbacks Notion uses on some payloads.
    title = rich_text_to_plain(obj.get("title"))
    return title or "(untitled)"


def _date_value(raw: Any) -> str | None:
    if not isinstance(raw, dict):
        return None
    start = raw.get("start")
    end = raw.get("end")
    if start and end:
        return f"{start} → {end}"
    return start or None


def _person_name(person: Any) -> str:
    if not isinstance(person, dict):
        return ""
    return str(person.get("name") or person.get("id") or "")


def property_value(prop: Any) -> Any:
    """Flatten one Notion property object into a plain scalar / list / None."""
    if not isinstance(prop, dict):
        return None
    ptype = prop.get("type")
    if ptype == "title":
        return rich_text_to_plain(prop.get("title")) or None
    if ptype == "rich_text":
        return rich_text_to_plain(prop.get("rich_text")) or None
    if ptype == "number":
        return prop.get("number")
    if ptype == "checkbox":
        return bool(prop.get("checkbox"))
    if ptype in ("url", "email", "phone_number"):
        return prop.get(ptype)
    if ptype in ("select", "status"):
        option = prop.get(ptype) or {}
        return option.get("name") if isinstance(option, dict) else None
    if ptype == "multi_select":
        options = prop.get("multi_select") or []
        return [o.get("name") for o in options if isinstance(o, dict) and o.get("name")]
    if ptype == "date":
        return _date_value(prop.get("date"))
    if ptype == "people":
        names = [_person_name(p) for p in (prop.get("people") or [])]
        return [n for n in names if n]
    if ptype in ("created_time", "last_edited_time"):
        return prop.get(ptype)
    if ptype == "formula":
        formula = prop.get("formula") or {}
        ftype = formula.get("type")
        return formula.get(ftype) if isinstance(formula, dict) and ftype else None
    return None


def flatten_properties(props: Any) -> dict[str, Any]:
    """`{property name: plain value}` for every property with a value."""
    if not isinstance(props, dict):
        return {}
    out: dict[str, Any] = {}
    for name, prop in props.items():
        value = property_value(prop)
        if value is None or value == [] or value == "":
            continue
        out[str(name)] = value
    return out
