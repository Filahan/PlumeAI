"""Reference resolution for `{{ path }}` templates used inside automation documents.

A reference path looks like `step_k3f9a.output.count` or `trigger.now`, optionally with
array indexing (`step_x.output.items[0].id`). The root segment is either a step id (in
which case the rest of the path is resolved against `{"output": <that step's output>}`)
or the literal `trigger` (resolved against a small context dict with `now`/`date`/
`timezone` keys).

Step outputs and the trigger context are plain JSON-shaped data (the output of decoding
a JSON document: `dict`, `list`, `str`, `int`, `float`, `bool`, `None`), never arbitrary
Python objects — so path resolution only ever indexes into `dict`/`list`/`tuple` and
never falls back to `getattr`. That's a deliberate security boundary, not just a type
restriction: without it, a path like `{{step_x.output.__class__.__base__}}` would be
able to walk arbitrary Python object internals.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from app.schemas.refs import REF_PATH_SOURCE, REF_RE

if TYPE_CHECKING:
    from app.schemas.documents import FieldValue

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|\[\d+\]")

__all__ = [
    "REF_PATH_SOURCE",
    "REF_RE",
    "RefError",
    "interpolate",
    "parse_refs",
    "ref_step_id",
    "ref_tokens",
    "resolve_field",
    "resolve_path",
    "resolve_ref",
]


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


def ref_tokens(path: str) -> list[str]:
    """Split a reference path into its segments, e.g. 'step_x.output.items[0].id' →
    `['step_x', 'output', 'items', '[0]', 'id']`. Index segments keep their brackets so
    a caller can tell `items[0]` from a key literally named `0`. Raises `RefError` when
    the path has no parseable segment at all."""
    return _tokenize(path)


def ref_step_id(path: str) -> str:
    """Return the first (root) segment of a reference path, e.g. 'step_x' from 'step_x.output'."""
    return ref_tokens(path)[0]


def _walk(root: Any, tokens: list[str], path: str) -> Any:
    current = root
    for tok in tokens:
        if tok.startswith("["):
            index = int(tok[1:-1])
            if not isinstance(current, (list, tuple)):
                raise RefError(
                    f"cannot index into {type(current).__name__} while resolving {path!r}"
                )
            try:
                current = current[index]
            except (IndexError, KeyError, TypeError) as exc:
                raise RefError(f"index {index} not found while resolving {path!r}") from exc
        else:
            if not isinstance(current, dict):
                raise RefError(
                    f"cannot look up key {tok!r} on {type(current).__name__} "
                    f"while resolving {path!r}"
                )
            try:
                current = current[tok]
            except KeyError as exc:
                raise RefError(f"key {tok!r} not found while resolving {path!r}") from exc
    return current


def resolve_path(root: Any, path: str) -> Any:
    """Walk `path` (e.g. 'a.b.c' or 'a[0].b') starting at `root`.

    Only `dict` (for `.name` segments) and `list`/`tuple` (for `[index]` segments) are
    traversed; anything else raises `RefError`.
    """
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
    """Replace every `{{ ref }}` in `template` with its resolved value (as a string).

    Scalars are rendered with `str()` *except* `bool`/`None`, which are rendered as
    their JSON spellings (`true`/`false`/`null`) rather than Python's (`True`/`False`/
    `None`) — the template is meant to read as JSON-ish text embedded in a sentence, not
    as a Python repr. `dict`/`list` values are rendered as compact JSON.
    """

    def _replace(match: re.Match[str]) -> str:
        value = resolve_ref(outputs, ctx, match.group(1))
        if value is None or isinstance(value, (dict, list, bool)):
            return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        return str(value)

    return REF_RE.sub(_replace, template)


def resolve_field(fv: FieldValue, outputs: dict[str, Any], ctx: dict[str, Any]) -> Any:
    """Resolve a `FieldValue` to its runtime value."""
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
