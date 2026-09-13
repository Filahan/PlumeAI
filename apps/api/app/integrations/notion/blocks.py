"""Markdown ⇄ Notion block conversion.

Notion's API takes structured blocks rather than text, so every write path needs a
converter. This is a deliberately small subset — headings, bullets, numbered lists,
code fences and paragraphs — which is what an LLM writing a page actually emits.
"""

from __future__ import annotations

import re
from typing import Any

# Notion rejects any rich-text item longer than 2000 characters, so long paragraphs are
# split into several blocks rather than truncated.
MAX_TEXT_CHARS = 2000
# A single children request accepts at most 100 blocks; the caller appends the remainder.
MAX_BLOCKS_PER_REQUEST = 100

_NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
_TODO_RE = re.compile(r"^\s*[-*+]\s+\[( |x|X)\]\s+(.*)$")
_FENCE_RE = re.compile(r"^\s*```\s*([A-Za-z0-9+#._-]*)\s*$")

# Notion only accepts languages from its own enum; map the aliases people type.
_LANGUAGE_ALIASES = {
    "py": "python",
    "js": "javascript",
    "jsx": "javascript",
    "ts": "typescript",
    "tsx": "typescript",
    "sh": "shell",
    "zsh": "shell",
    "yml": "yaml",
    "md": "markdown",
    "": "plain text",
}


def _text(content: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": content}}]


def _chunks(text: str) -> list[str]:
    """Split `text` into ≤ MAX_TEXT_CHARS pieces, preferring a space boundary."""
    if len(text) <= MAX_TEXT_CHARS:
        return [text]
    out: list[str] = []
    rest = text
    while len(rest) > MAX_TEXT_CHARS:
        window = rest[:MAX_TEXT_CHARS]
        cut = window.rfind(" ")
        if cut < MAX_TEXT_CHARS // 2:  # no usable boundary — hard split
            cut = MAX_TEXT_CHARS
        out.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        out.append(rest)
    return out


def _blocks_of(kind: str, text: str, extra: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """One block per ≤2000-char chunk of `text`, all of the same `kind`."""
    out: list[dict[str, Any]] = []
    for chunk in _chunks(text):
        payload: dict[str, Any] = {"rich_text": _text(chunk)}
        if extra:
            payload.update(extra)
        out.append({"object": "block", "type": kind, kind: payload})
    return out


def _code_block(code: str, language: str) -> dict[str, Any]:
    lang = _LANGUAGE_ALIASES.get(language.lower(), language.lower() or "plain text")
    return {
        "object": "block",
        "type": "code",
        "code": {"rich_text": _text(code[: MAX_TEXT_CHARS * 10]), "language": lang},
    }


def markdown_to_blocks(content: str) -> list[dict[str, Any]]:
    """Convert markdown-ish text into Notion blocks.

    Supported: `#`/`##`/`###` headings, `-`/`*`/`+` bullets (including `- [ ]` to-dos),
    `1.` numbered items, `>` quotes, `---` dividers, ``` fenced code, and blank-line
    separated paragraphs. Anything else becomes paragraph text.
    """
    blocks: list[dict[str, Any]] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.extend(_blocks_of("paragraph", "\n".join(paragraph).strip()))
            paragraph.clear()

    lines = (content or "").replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        fence = _FENCE_RE.match(line)
        if fence:
            flush()
            language = fence.group(1)
            body: list[str] = []
            i += 1
            while i < len(lines) and not _FENCE_RE.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1  # consume the closing fence (or fall off the end)
            blocks.append(_code_block("\n".join(body), language))
            continue

        stripped = line.strip()
        if not stripped:
            flush()
        elif stripped in ("---", "***", "___"):
            flush()
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        elif stripped.startswith("### "):
            flush()
            blocks.extend(_blocks_of("heading_3", stripped[4:].strip()))
        elif stripped.startswith("## "):
            flush()
            blocks.extend(_blocks_of("heading_2", stripped[3:].strip()))
        elif stripped.startswith("# "):
            flush()
            blocks.extend(_blocks_of("heading_1", stripped[2:].strip()))
        elif stripped.startswith("> "):
            flush()
            blocks.extend(_blocks_of("quote", stripped[2:].strip()))
        elif _TODO_RE.match(line):
            flush()
            m = _TODO_RE.match(line)
            assert m is not None
            blocks.extend(
                _blocks_of("to_do", m.group(2).strip(), {"checked": m.group(1).lower() == "x"})
            )
        elif _BULLET_RE.match(line):
            flush()
            m = _BULLET_RE.match(line)
            assert m is not None
            blocks.extend(_blocks_of("bulleted_list_item", m.group(1).strip()))
        elif _NUMBERED_RE.match(line):
            flush()
            m = _NUMBERED_RE.match(line)
            assert m is not None
            blocks.extend(_blocks_of("numbered_list_item", m.group(1).strip()))
        else:
            paragraph.append(stripped)
        i += 1

    flush()
    return blocks


# ─── blocks → readable text (the read path) ──────────────────────────────────────────

_PREFIXES = {
    "heading_1": "# ",
    "heading_2": "## ",
    "heading_3": "### ",
    "bulleted_list_item": "- ",
    "numbered_list_item": "1. ",
    "quote": "> ",
    "callout": "> ",
    "toggle": "",
    "paragraph": "",
}


def blocks_to_text(blocks: list[dict[str, Any]]) -> str:
    """Render Notion blocks back to markdown-ish text for the LLM to read."""
    from app.integrations.notion.client import rich_text_to_plain

    lines: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = str(block.get("type") or "")
        payload = block.get(btype) if isinstance(block.get(btype), dict) else {}
        if btype == "divider":
            lines.append("---")
            continue
        if btype == "code":
            language = str((payload or {}).get("language") or "")
            body = rich_text_to_plain((payload or {}).get("rich_text"))
            lines.append(f"```{language}\n{body}\n```")
            continue
        if btype == "child_page":
            lines.append(f"[page] {(payload or {}).get('title') or ''}")
            continue
        if btype == "child_database":
            lines.append(f"[database] {(payload or {}).get('title') or ''}")
            continue
        if btype == "to_do":
            box = "[x]" if (payload or {}).get("checked") else "[ ]"
            lines.append(f"- {box} {rich_text_to_plain((payload or {}).get('rich_text'))}")
            continue
        text = rich_text_to_plain((payload or {}).get("rich_text"))
        if not text:
            continue
        lines.append(f"{_PREFIXES.get(btype, '')}{text}")
    return "\n".join(lines).strip()
