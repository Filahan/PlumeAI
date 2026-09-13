"""Tests for `app.services.refs`: parsing, path resolution, and interpolation.

Pure functions only — no network, no DB.
"""

from __future__ import annotations

import pytest

from app.schemas.documents import FieldValue
from app.services.refs import (
    RefError,
    interpolate,
    parse_refs,
    ref_step_id,
    resolve_field,
    resolve_path,
    resolve_ref,
)

# --- parse_refs / ref_step_id --------------------------------------------------------------


def test_parse_refs_finds_all_references() -> None:
    text = "From {{step_a.output.name}} to {{step_b.output}}."
    assert parse_refs(text) == ["step_a.output.name", "step_b.output"]


def test_parse_refs_returns_empty_list_when_no_refs() -> None:
    assert parse_refs("no refs here") == []


def test_parse_refs_trims_internal_whitespace() -> None:
    assert parse_refs("{{ step_a.output }}") == ["step_a.output"]


def test_ref_step_id_returns_root_segment() -> None:
    assert ref_step_id("step_a.output.count") == "step_a"
    assert ref_step_id("step_a[0].name") == "step_a"
    assert ref_step_id("trigger.now") == "trigger"


# --- resolve_path ----------------------------------------------------------------------------


def test_resolve_path_dotted() -> None:
    root = {"a": {"b": {"c": 42}}}
    assert resolve_path(root, "a.b.c") == 42


def test_resolve_path_with_array_index() -> None:
    root = {"a": [{"b": 1}, {"b": 2}]}
    assert resolve_path(root, "a[1].b") == 2


def test_resolve_path_preserves_types() -> None:
    root = {"a": {"count": 3, "flag": True, "items": [1, 2, 3], "nested": {"x": 1}}}
    assert resolve_path(root, "a.count") == 3
    assert resolve_path(root, "a.flag") is True
    assert resolve_path(root, "a.items") == [1, 2, 3]
    assert resolve_path(root, "a.nested") == {"x": 1}


def test_resolve_path_raises_ref_error_on_missing_key() -> None:
    with pytest.raises(RefError):
        resolve_path({"a": 1}, "b")


def test_resolve_path_raises_ref_error_on_bad_index() -> None:
    with pytest.raises(RefError):
        resolve_path({"a": [1, 2]}, "a[5]")


def test_resolve_path_error_message_includes_path() -> None:
    with pytest.raises(RefError, match="a.b.c"):
        resolve_path({"a": {"b": {}}}, "a.b.c")


# --- resolve_ref -----------------------------------------------------------------------------


def test_resolve_ref_step_output() -> None:
    outputs = {"step_a": {"count": 3}}
    ctx: dict = {}
    assert resolve_ref(outputs, ctx, "step_a.output.count") == 3


def test_resolve_ref_whole_output() -> None:
    outputs = {"step_a": {"count": 3}}
    assert resolve_ref(outputs, {}, "step_a.output") == {"count": 3}


def test_resolve_ref_trigger_context() -> None:
    ctx = {"now": "2026-09-13T08:00:00", "date": "2026-09-13", "timezone": "Europe/Paris"}
    assert resolve_ref({}, ctx, "trigger.date") == "2026-09-13"


def test_resolve_ref_unknown_root_raises() -> None:
    with pytest.raises(RefError):
        resolve_ref({}, {}, "step_ghost.output")


# --- interpolate -----------------------------------------------------------------------------


def test_interpolate_replaces_scalar_values() -> None:
    outputs = {"step_a": {"name": "Dana"}}
    result = interpolate("Hello {{step_a.output.name}}!", outputs, {})
    assert result == "Hello Dana!"


def test_interpolate_renders_dict_as_compact_json() -> None:
    outputs = {"step_a": {"count": 3, "flag": True}}
    result = interpolate("Data: {{step_a.output}}", outputs, {})
    assert result == 'Data: {"count":3,"flag":true}'


def test_interpolate_renders_list_as_compact_json() -> None:
    outputs = {"step_a": [1, 2, 3]}
    result = interpolate("Items: {{step_a.output}}", outputs, {})
    assert result == "Items: [1,2,3]"


def test_interpolate_multiple_refs() -> None:
    outputs = {"step_a": {"x": 1}, "step_b": {"y": 2}}
    result = interpolate("{{step_a.output.x}} and {{step_b.output.y}}", outputs, {})
    assert result == "1 and 2"


# --- resolve_field ---------------------------------------------------------------------------


def test_resolve_field_literal_string_is_interpolated() -> None:
    fv = FieldValue(kind="literal", value="Hi {{step_a.output.name}}")
    assert resolve_field(fv, {"step_a": {"name": "Dana"}}, {}) == "Hi Dana"


def test_resolve_field_literal_non_string_passthrough() -> None:
    fv = FieldValue(kind="literal", value=42)
    assert resolve_field(fv, {}, {}) == 42


def test_resolve_field_ref_returns_raw_typed_value() -> None:
    fv = FieldValue(kind="ref", value="{{step_a.output.count}}")
    assert resolve_field(fv, {"step_a": {"count": 7}}, {}) == 7


def test_resolve_field_ai_raises_not_implemented() -> None:
    fv = FieldValue(kind="ai", value="Guess the count")
    with pytest.raises(NotImplementedError):
        resolve_field(fv, {}, {})
