"""Grammar for `{{ path }}` reference-path templates — the single source of truth.

This is a **leaf module**: it must not import from `app.services` (or anything that
does). Both `app.schemas.documents` (to validate a `kind: "ref"` `FieldValue.value` at
parse time) and `app.services.refs` (to find/resolve paths at runtime) import from
here, so putting the grammar in either of those two modules would create an import
cycle the moment the other one needed it too.
"""

from __future__ import annotations

import re

# A path is a step id (or `trigger`) followed by any number of `.name` / `[index]`
# segments, e.g. `step_x`, `step_x.output.count`, `step_x.output.items[0].id`.
REF_PATH_SOURCE = r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+|\[\d+\])*"

# Non-anchored: finds every `{{ path }}` occurrence inside a larger string (used by
# `parse_refs`/`interpolate` to scan free text such as AI instructions).
REF_RE = re.compile(r"\{\{\s*(" + REF_PATH_SOURCE + r")\s*\}\}")

# Anchored end-to-end with `\Z` and meant to be checked with `.fullmatch()`: the
# *entire* string must be exactly one `{{ path }}` reference — used to validate a
# `kind: "ref"` `FieldValue.value`, which must not be a larger template with other text
# around it.
REF_FULLMATCH_RE = re.compile(r"\{\{\s*" + REF_PATH_SOURCE + r"\s*\}\}\Z")
