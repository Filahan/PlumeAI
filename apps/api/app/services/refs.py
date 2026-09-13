"""Reference resolution for `{{ path }}` templates used inside automation documents.

A reference path looks like `step_k3f9a.output.count` or `trigger.now`, optionally with
array indexing (`step_x.output.items[0].id`). The root segment is either a step id (in
which case the rest of the path is resolved against `{"output": <that step's output>}`)
or the literal `trigger` (resolved against a small context dict with `now`/`date`/
`timezone` keys).
"""

from __future__ import annotations

import json
import re
from typing import Any

REF_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+|\[\d+\])*)\s*\}\}")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|\[\d+\]")


class RefError(ValueError):
    """Raised when a `{{ ... }}` reference path cannot be resolved."""


def parse_refs(text: str) -> list[str]:
    """Return the raw paths (without braces) of every `{{ ... }}` reference in `text`."""
    return REF_RE.findall(text)


def _tokenize(path: str) -> list[str]:
    tokens = _TOKEN_RE.findall(path)
    if not tokens:
        raise RefError(f"cannot parse reference path: {path!r}")
    return tokens


def ref_step_id(path: str) -> str:
    """Return the first (root) segment of a reference path, e.g. 'step_x' from 'step_x.output'."""
    return _tokenize(path)[0]


def _walk(root: Any, tokens: list[str], path: str) -> Any:
    current = root
    for tok in tokens:
        if tok.startswith("["):
            index = int(tok[1:-1])
            try:
                current = current[index]
            except (IndexError, TypeError) as exc:
                raise RefError(f"index {index} not found while resolving {path!r}") from exc
        else:
            try:
                current = current[tok] if isinstance(current, dict) else getattr(current, tok)
            except (KeyError, AttributeError, TypeError) as exc:
                raise RefError(f"key {tok!r} not found while resolving {path!r}") from exc
    return current


def resolve_path(root: Any, path: str) -> Any:
    """Walk `path` (e.g. 'a.b.c' or 'a[0].b') starting at `root`."""
    return _walk(root, _tokenize(path), path)


def resolve_ref(outputs: dict[str, Any], ctx: dict[str, Any], path: str) -> Any:
    """Resolve a reference path against step `outputs` and the trigger `ctx`."""
    tokens = _tokenize(path)
    root_id = tokens[0]
    if root_id == "trigger":
        root_obj: Any = ctx
    elif root_id in outputs:
        root_obj = {"output": outputs[root_id]}
    else:
        raise RefError(f"unknown reference root {root_id!r} while resolving {path!r}")
    return _walk(root_obj, tokens[1:], path)


def interpolate(template: str, outputs: dict[str, Any], ctx: dict[str, Any]) -> str:
    """Replace every `{{ ref }}` in `template` with its resolved value (as a string)."""

    def _replace(match: re.Match[str]) -> str:
        value = resolve_ref(outputs, ctx, match.group(1))
        if isinstance(value, (dict, list)):
            return json.dumps(value, separators=(",", ":"))
        return str(value)

    return REF_RE.sub(_replace, template)


def resolve_field(fv: Any, outputs: dict[str, Any], ctx: dict[str, Any]) -> Any:
    """Resolve a `FieldValue`-like object (has `.kind` and `.value`) to its runtime value."""
    if fv.kind == "literal":
        if isinstance(fv.value, str):
            return interpolate(fv.value, outputs, ctx)
        return fv.value
    if fv.kind == "ref":
        path = parse_refs(fv.value)[0]
        return resolve_ref(outputs, ctx, path)
    if fv.kind == "ai":
        raise NotImplementedError("ai fields are resolved by the executor, not resolve_field")
    raise ValueError(f"unknown FieldValue kind: {fv.kind!r}")
