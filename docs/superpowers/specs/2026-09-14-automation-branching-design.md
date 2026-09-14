# Branching automations: the `router` step

**Status:** approved 2026-09-14
**Branch:** `feat/automation-builder`

## Problem

An automation document is one trigger plus a flat, ordered `steps` list
(`apps/api/app/schemas/documents.py:265`). Every run walks that list start to finish
(`apps/api/app/services/executor.py:466`). The only way to alter the path is a `filter`
step, which does not choose between paths — it stops the run outright.

So an automation cannot express "if the invoice is over 1000 €, send it for approval;
otherwise file it". Users have to build one automation per case and duplicate the steps
they share.

## Goal

Add a `router` step that splits the flow into named branches, each guarded by a
condition. Keep everything else — run history, SSE, refs, the JSON view — working as it
does today.

## Non-goals

- **Merge / join.** Branches do not reconverge. A run that enters a branch ends there.
- **Parallel execution.** Selected branches run one after another, in order.
- **Loops / iterators.** Out of scope.

These were considered and deliberately declined; the model below is chosen partly
because it does not foreclose them.

## 1. Document language

### The router step

```python
class Branch(DocSchema):
    id: str = Field(pattern=r"^br_[a-z0-9]{5,}$")
    name: str
    condition: Predicate | None = None      # None => default branch
    steps: list[Step] = Field(default_factory=list)


class RouterSettings(DocSchema):
    branches: list[Branch] = Field(min_length=1)


class RouterStep(StepBase):
    type: Literal["router"] = "router"
    settings: RouterSettings
```

`RouterStep` joins the `Step` union. Because `Branch.steps` is itself `list[Step]`, the
model is recursive and needs `model_rebuild()` after the union is defined.

### Reusing the filter's predicate

The current `FilterSettings` (`documents.py:165`) is already exactly the shape a branch
condition needs: `{mode: "rules" | "ai", rules, instruction}`. Extract it as `Predicate`
and leave `class FilterSettings(Predicate): pass` behind. The `filter` step is untouched,
and branch conditions inherit the twelve operators and the `ai` mode for free.

### Validation rules

1. **A router must be the last step of its list.** Steps following a router at the same
   level would run after every selected branch — that is a join, which is a non-goal, and
   it would make `{{step_x}}` refs ambiguous (did the step that produced `step_x` run?).
   Anything that should follow the decision goes inside the branches.
2. At most one branch has `condition: None`, and it must be last.
3. Branch ids are unique across the whole document.
4. Step ids are unique across the whole document — `_unique_step_ids`
   (`documents.py:272`) becomes a tree walk instead of a `Counter` over a flat list.
5. Routers nest at most 5 deep. Not a product constraint; a guard so a pathological
   document — or a runaway assistant edit — cannot blow up canvas layout.

A document with no router is unchanged and still valid. No format version, no migration.

## 2. Execution semantics

### Run rows stay positional

`run_steps` rows are pre-created from the pinned document
(`apps/api/app/services/runs.py:151`). That `enumerate` becomes a **pre-order walk** of
the tree; `index` is the pre-order position.

This is the load-bearing choice. In pre-order, **a step's subtree occupies a contiguous
index range**, so:

- the `run_steps` table, its `index` column, and the SSE payloads
  (`{stepId, index, status}`) keep their exact current shape;
- skipping a branch that was not taken is a range update, not a graph traversal.

`skip_from(index)` (`executor.py:421`) gains a sibling `skip_range(start, end)`. Cancel
(`abort`, `executor.py:440`) can no longer assume "everything after the cursor" and
instead skips every row still in an active status.

### The loop

`run_steps()` (`executor.py:464`) becomes recursive over a list of steps plus a base
index. On a `router` step:

1. Evaluate branch conditions in document order.
2. **Selected = every branch whose condition is true.** The default branch is selected
   only if no conditioned branch matched.
3. Run the selected branches in order, sequentially, recursing into each.
4. Mark the full index range of every non-selected branch `skipped`.

The router row itself finishes `succeeded`, with output
`{"taken": [{"id": "br_x", "name": "Urgent"}, ...]}` — so the run history answers "why
did it go that way", and a later step can reference it.

A router where nothing matches and there is no default branch is not an error: it
succeeds having taken nothing.

### Stopping and failing

- A **`filter` inside a branch ends that branch**: the rest of that branch's steps are
  skipped and the enclosing router moves on to its next selected branch. At the document
  root, a filter still ends the run, as today.
- `Run.stopped_by_step_id` is a single column, but several branches can now each be cut
  short. It keeps its narrow meaning — **the filter that ended the whole run**, i.e. a
  root-level one — and stays null when only branches were stopped. Branch-local stops are
  already legible from the skipped `run_steps` rows, so no schema change is needed.
- A **failing step still fails the whole run**, wherever it sits. Branch-local error
  handling is not part of this work.

## 3. References and scope

Today a ref may point at any step strictly earlier in the flat list — `step_index` plus
an `idx` comparison (`apps/api/app/services/documents/validation.py:91`).

The tree rule: **a step may reference exactly those steps guaranteed to have run before
it** — its earlier siblings, its ancestor routers, and those ancestors' earlier siblings.
Never a step in another branch.

Implement it by carrying a `visible: dict[str, int]` down the same walk that validates
the tree. Entering a branch copies the accumulated set and adds the router; a branch's
contents never leak back out to its siblings.

When a ref's root exists in the document but is not visible, the error must say so
("`step_x` is in another branch and may not have run") rather than the current "unknown
step" — the shape of mistake this feature invites.

`ValidationIssue` gains a `step_id` field alongside `path`. The frontend currently finds
a step's problems by prefix-matching `steps[N]` (`use-canvas-selectors.ts:26`), which
does not survive nested paths; keying on the step id is both correct and simpler than
matching ever-longer paths.

## 4. Operations

Steps are addressed by a `(branch_id, index)` pair, where `branch_id: None` means the
document root. Branch ids are unique document-wide, so this is unambiguous and stable
across edits.

- `AddStep` gains `branch_id: str | None = None`. Existing payloads that pass only
  `index` keep targeting the root, so the assistant prompt and current tests keep working.
  An `index` that would land after a router in the target list is rejected — it would
  break rule 1.
- `MoveStep` gains the same field, and may move a step between branches. Moving a router
  into its own subtree is rejected.
- `RemoveStep` and `UpdateStep` find their target by a recursive lookup — `_find_index`
  (`operations.py:47`) becomes `_find_path`. Removing a router removes its subtree.

Four branch operations are added, because `update_step`'s one-level-deep `settings` merge
(`operations.py:54`) can only replace `branches` wholesale:

- `AddBranch(router_id, branch, index=None)`
- `UpdateBranch(branch_id, patch)` — `name` and `condition` only, never `steps`
- `RemoveBranch(branch_id)` — removes its steps too; refuses to remove the last branch
- `MoveBranch(branch_id, index)`

`AddBranch` and `MoveBranch` are rejected when the resulting order would leave the
default branch anywhere but last (rule 2). Turning a conditioned branch into the default
one, or vice versa, is an `UpdateBranch` on its `condition` and is subject to the same
rule.

## 5. Canvas and editor

Layout is already dagre (`use-auto-layout.ts:118`) over an explicit node/edge list, and
`@dagrejs/dagre` is in `package.json`. Emitting a tree's nodes and edges is enough;
positions follow. There is no drag-to-reorder (`nodesDraggable={false}`), so there is no
reordering path to port.

The real work is the **insertion address**. Every "+" affordance currently carries an
integer index, threaded through edges, add nodes, the store's
`stepPicker: {index}` (`store.ts:108`), and the picker dialog. It becomes
`{branchId: string | null, index: number}`.

Router rendering: one node with an output handle per branch; each edge labelled with the
branch name and a summary of its condition. An empty branch shows its own trailing "+".
Because a router ends its list, the "+" that would follow a router disappears.

Two changes that fall out:

- The `index + 1` position badge (`step-node.tsx:36`) is meaningless in a tree. Remove it
  rather than invent a hierarchical numbering.
- `opaque-field.ts:130` offers refs via `steps.slice(0, cut)`. It must implement the same
  visibility rule as section 3, or the editor will suggest refs that validation rejects.

`step-deep-link.tsx:30` and the assistant's before/after diff (`assistant-slice.ts:100`)
both scan `doc.steps` flat and need to recurse.

## 6. Assistant

The system prompt (`apps/api/app/services/assistant_prompt.py`) gains the `router` step
type, the four branch operations, the `branch_id` field, and the two rules most likely to
trip it: a router ends its list, and a step cannot reference another branch. The existing
self-correction loop then handles the rest — validation errors already feed back to it.

## 7. Testing

Backend (`docker compose exec -T api pytest -q tests`, one suite at a time — shared
`plumeai_test` DB):

- schema: recursion, depth limit, router-must-be-last, one default branch last, id
  uniqueness across the tree
- operations: add/move/remove/update at depth, the four branch ops, subtree removal,
  rejecting a move into own subtree
- validation: the visibility rule, including the cross-branch error message
- executor: multiple branches selected, default fallback, nothing matched, non-selected
  ranges skipped, filter ending a branch, failure inside a branch, cancel mid-branch,
  pre-order index contiguity

Frontend: `tsc` clean, plus the store's insertion-address changes.

## 8. Risks

- **Silent ref breakage.** The tightened scope rule can invalidate a document that was
  legal before only if it already contained a router — and none can, since the type is
  new. Existing documents are unaffected.
- **Frontend/backend scope drift.** `opaque-field.ts` and `validation.py` implement the
  same rule twice, in two languages. They must be specified once here and tested on both
  sides.
- **Canvas width.** Deep nesting grows horizontally. The depth limit of 5 bounds it; if
  it still reads badly, collapsing a branch is the follow-up, not part of this work.
