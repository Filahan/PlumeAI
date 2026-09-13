"""Tests for `app.services.filters.evaluate_rules`.

Pure functions only — no network, no DB.
"""

from __future__ import annotations

from app.schemas.documents import Condition, FieldValue, Rules
from app.services.filters import evaluate_rules

OUTPUTS = {"step_a": {"count": 3, "status": "OK", "tags": ["urgent", "billing"], "flag": True}}
CTX: dict = {}


def _lit(value):
    return FieldValue(kind="literal", value=value)


def _ref(path: str) -> FieldValue:
    return FieldValue(kind="ref", value="{{" + path + "}}")


def _rules(*conditions: Condition, combinator: str = "and") -> Rules:
    return Rules(combinator=combinator, conditions=list(conditions))


# --- individual ops --------------------------------------------------------------------------


def test_eq_true_and_false() -> None:
    result, _ = evaluate_rules(
        _rules(Condition(left=_ref("step_a.output.status"), op="eq", right=_lit("OK"))),
        OUTPUTS,
        CTX,
    )
    assert result is True

    result, _ = evaluate_rules(
        _rules(Condition(left=_ref("step_a.output.status"), op="eq", right=_lit("NO"))),
        OUTPUTS,
        CTX,
    )
    assert result is False


def test_neq() -> None:
    result, _ = evaluate_rules(
        _rules(Condition(left=_ref("step_a.output.status"), op="neq", right=_lit("NO"))),
        OUTPUTS,
        CTX,
    )
    assert result is True


def test_contains_case_insensitive_on_strings() -> None:
    result, _ = evaluate_rules(
        _rules(Condition(left=_ref("step_a.output.status"), op="contains", right=_lit("ok"))),
        OUTPUTS,
        CTX,
    )
    assert result is True


def test_contains_on_list_membership() -> None:
    result, _ = evaluate_rules(
        _rules(
            Condition(left=_ref("step_a.output.tags"), op="contains", right=_lit("urgent"))
        ),
        OUTPUTS,
        CTX,
    )
    assert result is True


def test_contains_on_list_of_strings_is_case_insensitive() -> None:
    result, _ = evaluate_rules(
        _rules(Condition(left=_ref("step_a.output.tags"), op="contains", right=_lit("URGENT"))),
        OUTPUTS,
        CTX,
    )
    assert result is True

    result, _ = evaluate_rules(
        _rules(
            Condition(left=_ref("step_a.output.tags"), op="not_contains", right=_lit("Billing"))
        ),
        OUTPUTS,
        CTX,
    )
    assert result is False  # "Billing" (case-insensitively) IS in the list


def test_contains_on_mixed_list_is_case_insensitive_for_string_items() -> None:
    result, _ = evaluate_rules(
        _rules(Condition(left=_lit(["Urgent", 3, None]), op="contains", right=_lit("urgent"))),
        OUTPUTS,
        CTX,
    )
    assert result is True

    result, _ = evaluate_rules(
        _rules(Condition(left=_lit(["Urgent", 3, None]), op="contains", right=_lit(3))),
        OUTPUTS,
        CTX,
    )
    assert result is True  # non-string items still compare with plain equality


def test_contains_on_dict_checks_keys_case_insensitively() -> None:
    result, _ = evaluate_rules(
        _rules(
            Condition(
                left=_lit({"Urgent": True, "billing": False}), op="contains", right=_lit("urgent")
            )
        ),
        OUTPUTS,
        CTX,
    )
    assert result is True


def test_reason_string_truncates_long_values() -> None:
    long_value = "x" * 500
    result, reason = evaluate_rules(
        _rules(Condition(left=_lit(long_value), op="is_not_empty")), OUTPUTS, CTX
    )
    assert result is True
    assert reason.count("x") < 500  # the repr got cut off, not displayed in full
    assert "…" in reason


def test_contains_on_non_string_non_collection_left_returns_false_not_raise() -> None:
    result, reason = evaluate_rules(
        _rules(Condition(left=_ref("step_a.output.count"), op="contains", right=_lit("3"))),
        OUTPUTS,
        CTX,
    )
    assert result is False
    assert reason  # a reason string is still produced, no exception escaped


def test_not_contains() -> None:
    result, _ = evaluate_rules(
        _rules(
            Condition(left=_ref("step_a.output.status"), op="not_contains", right=_lit("zzz"))
        ),
        OUTPUTS,
        CTX,
    )
    assert result is True


def test_numeric_comparisons() -> None:
    for op, right, expected in [("gt", 0, True), ("gt", 5, False), ("gte", 3, True),
                                 ("lt", 5, True), ("lte", 3, True), ("lte", 2, False)]:
        result, _ = evaluate_rules(
            _rules(Condition(left=_ref("step_a.output.count"), op=op, right=_lit(right))),
            OUTPUTS,
            CTX,
        )
        assert result is expected, f"op={op} right={right}"


def test_numeric_comparison_coerces_numeric_strings() -> None:
    result, _ = evaluate_rules(
        _rules(Condition(left=_lit("10"), op="gt", right=_lit("2"))),
        OUTPUTS,
        CTX,
    )
    assert result is True  # numeric coercion, not lexicographic ("10" < "2" as strings)


def test_is_empty_and_is_not_empty() -> None:
    cases = [(None, True), ("", True), ([], True), ({}, True), ("x", False), (0, False)]
    for value, empty_expected in cases:
        result, _ = evaluate_rules(
            _rules(Condition(left=_lit(value), op="is_empty")), OUTPUTS, CTX
        )
        assert result is empty_expected, f"value={value!r}"

        result, _ = evaluate_rules(
            _rules(Condition(left=_lit(value), op="is_not_empty")), OUTPUTS, CTX
        )
        assert result is (not empty_expected), f"value={value!r}"


def test_is_true_and_is_false() -> None:
    result, _ = evaluate_rules(
        _rules(Condition(left=_ref("step_a.output.flag"), op="is_true")), OUTPUTS, CTX
    )
    assert result is True

    result, _ = evaluate_rules(
        _rules(Condition(left=_ref("step_a.output.flag"), op="is_false")), OUTPUTS, CTX
    )
    assert result is False


# --- combinators -------------------------------------------------------------------------------


def test_and_combinator_requires_all_true() -> None:
    cond_true = Condition(left=_ref("step_a.output.count"), op="gt", right=_lit(0))
    cond_false = Condition(left=_ref("step_a.output.count"), op="gt", right=_lit(100))

    result, _ = evaluate_rules(_rules(cond_true, cond_true, combinator="and"), OUTPUTS, CTX)
    assert result is True

    result, _ = evaluate_rules(_rules(cond_true, cond_false, combinator="and"), OUTPUTS, CTX)
    assert result is False


def test_or_combinator_requires_any_true() -> None:
    cond_true = Condition(left=_ref("step_a.output.count"), op="gt", right=_lit(0))
    cond_false = Condition(left=_ref("step_a.output.count"), op="gt", right=_lit(100))

    result, _ = evaluate_rules(_rules(cond_false, cond_false, combinator="or"), OUTPUTS, CTX)
    assert result is False

    result, _ = evaluate_rules(_rules(cond_true, cond_false, combinator="or"), OUTPUTS, CTX)
    assert result is True


# --- reason text -------------------------------------------------------------------------------


def test_reason_text_single_condition() -> None:
    result, reason = evaluate_rules(
        _rules(Condition(left=_ref("step_a.output.count"), op="gt", right=_lit(0))),
        OUTPUTS,
        CTX,
    )
    assert result is True
    assert reason == "count (3) > 0 → true"


def test_reason_text_unary_condition() -> None:
    result, reason = evaluate_rules(
        _rules(Condition(left=_lit(""), op="is_empty")), OUTPUTS, CTX
    )
    assert result is True
    assert reason == "'' ('') is empty → true"


def test_reason_text_combines_multiple_conditions() -> None:
    cond_a = Condition(left=_ref("step_a.output.count"), op="gt", right=_lit(0))
    cond_b = Condition(left=_ref("step_a.output.status"), op="eq", right=_lit("OK"))
    result, reason = evaluate_rules(_rules(cond_a, cond_b, combinator="and"), OUTPUTS, CTX)
    assert result is True
    assert "count (3) > 0 → true" in reason
    assert "status ('OK') == 'OK' → true" in reason
    assert reason.endswith("⇒ true")
