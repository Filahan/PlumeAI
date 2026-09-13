"""Pure, DB-free operations on `AutomationDocument`: applying edit operations,
validating against an action catalog, and summarizing the diff between two versions.

Split across `operations.py` (`apply_operations`, `new_step_id`, `dump_document`),
`validation.py` (`validate_document`, `ActionMeta`, `ActionCatalog`), and `diff.py`
(`diff_summary`, `describe_trigger`) — this `__init__` re-exports the public surface so
`from app.services.documents import validate_document` (etc.) keeps working exactly as
it did when this was a single module.
"""

from __future__ import annotations

from app.services.documents.diff import describe_trigger, diff_summary
from app.services.documents.operations import apply_operations, dump_document, new_step_id
from app.services.documents.validation import ActionCatalog, ActionMeta, validate_document

__all__ = [
    "ActionCatalog",
    "ActionMeta",
    "apply_operations",
    "describe_trigger",
    "diff_summary",
    "dump_document",
    "new_step_id",
    "validate_document",
]
