"""Evaluation of `filter` step rules against resolved step outputs."""

from __future__ import annotations

from typing import Any

from app.schemas.documents import Condition, Rules
from app.services.refs import parse_refs, resolve_field

_OP_SYMBOLS: dict[str, str] = {
    "eq": "==",
    "neq": "!=",
    "contains": "contains",
    "not_contains": "does not contain",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "is_empty": "is empty",
    "is_not_empty": "is not empty",
    "is_true": "is true",
    "is_false": "is false",
}

_UNARY_OPS = {"is_empty", "is_not_empty", "is_true", "is_false"}


def _label(fv: Any) -> str:
    if fv.kind == "ref":
        # e.g. "{{step_x.output.count}}" -> "count"
        path = parse_refs(fv.value)[0]
        return path.rsplit(".", 1)[-1].rsplit("[", 1)[0]
    return repr(fv.value)


def _is_empty(value: Any) -> bool:
    return value is None or value in ("", [], {})


def _as_number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError(f"cannot compare boolean {value!r} numerically")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError as exc:
            raise ValueError(f"cannot compare non-numeric string {value!r}") from exc
    raise ValueError(f"cannot compare non-numeric value {value!r}")


def _contains(left: Any, right: Any) -> bool:
    if isinstance(left, str):
        return str(right).lower() in left.lower()
    if isinstance(left, (list, tuple, set)):
        items = list(left)
        if isinstance(right, str) and all(isinstance(item, str) for item in items):
            return right.lower() in [item.lower() for item in items]
        return right in items
    if isinstance(left, dict):
        return right in left
    # Not a string/list/dict: no meaningful "contains" — treat as false, not a crash.
    return False


def _apply_op(op: str, left: Any, right: Any) -> bool:
    if op == "eq":
        return left == right
    if op == "neq":
        return left != right
    if op == "contains":
        return _contains(left, right)
    if op == "not_contains":
        return not _contains(left, right)
    if op == "gt":
        return _as_number(left) > _as_number(right)
    if op == "gte":
        return _as_number(left) >= _as_number(right)
    if op == "lt":
        return _as_number(left) < _as_number(right)
    if op == "lte":
        return _as_number(left) <= _as_number(right)
    if op == "is_empty":
        return _is_empty(left)
    if op == "is_not_empty":
        return not _is_empty(left)
    if op == "is_true":
        return bool(left)
    if op == "is_false":
        return not bool(left)
    raise ValueError(f"unknown condition op: {op!r}")


def _evaluate_condition(
    cond: Condition, outputs: dict[str, Any], ctx: dict[str, Any]
) -> tuple[bool, str]:
    left_value = resolve_field(cond.left, outputs, ctx)
    symbol = _OP_SYMBOLS[cond.op]
    label = _label(cond.left)

    if cond.op in _UNARY_OPS:
        result = _apply_op(cond.op, left_value, None)
        reason = f"{label} ({left_value!r}) {symbol} → {str(result).lower()}"
        return result, reason

    right_value = resolve_field(cond.right, outputs, ctx) if cond.right is not None else None
    result = _apply_op(cond.op, left_value, right_value)
    reason = f"{label} ({left_value!r}) {symbol} {right_value!r} → {str(result).lower()}"
    return result, reason


def evaluate_rules(rules: Rules, outputs: dict[str, Any], ctx: dict[str, Any]) -> tuple[bool, str]:
    """Evaluate a `Rules` tree, returning `(passed, reason)`."""
    results: list[bool] = []
    reasons: list[str] = []
    for cond in rules.conditions:
        result, reason = _evaluate_condition(cond, outputs, ctx)
        results.append(result)
        reasons.append(reason)

    final = all(results) if rules.combinator == "and" else any(results)
    joiner = " and " if rules.combinator == "and" else " or "
    combined = joiner.join(reasons)
    if len(reasons) > 1:
        combined = f"{combined} ⇒ {str(final).lower()}"
    return final, combined
