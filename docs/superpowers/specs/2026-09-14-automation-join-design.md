# Reconverging branches: the `join` step

**Status:** approved 2026-09-14
**Branch:** `feat/automation-builder`
**Extends:** [`2026-09-14-automation-branching-design.md`](./2026-09-14-automation-branching-design.md)

## Problem

The router design gives an automation named, conditioned branches, but it closes them:
"Branches do not reconverge. A run that enters a branch ends there." Rule 1 — *a router
must be the last step of its list* — is what enforces that.

So anything shared after a decision has to be duplicated into every branch. "If the
invoice is over 1000 €, get approval, otherwise file it — then, either way, notify the
submitter" needs the notify step written twice, and kept in sync by hand. Users
comparing PlumeAI to n8n reach for its Merge node and find nothing.

## Goal

Add a `join` step that ends a router's branches and continues the flow with a single
merged output. Keep `run_steps`, the SSE payloads, the Gantt, and the reference
visibility rule exactly as the router design leaves them.

## Non-goals

Unchanged from the router design, and for the same reasons:

- **Parallel execution.** Selected branches still run one after another, in order.
- **Loops / iterators.**
- **Branch-local error handling.** A failing step still fails the whole run.

And newly declined here:

- **`combine` and `chooseBranch` merge modes.** `JoinSettings.mode` exists as a
  `Literal["append"]` so that adding them later is a widened literal and a new executor
  branch, not a format change. One mode is one thing to specify, test, and teach the
  assistant.
- **A join that names its router by id and sits anywhere downstream.** It would break the
  contiguous pre-order index range the router design is built on (see §2).

## Why a sibling step

Three shapes were considered.

**A join as a field of the router** (`router.settings.join`) adds no step type, but the
router's `run_steps` row would have to finish *after* its children — inverting the
"parent completes, then children run" order the pre-order walk produces — and the merge
would have no row of its own in the run history or the Gantt.

**A join referencing a router by id**, placeable anywhere later, is the most free. It
also ends the contiguity guarantee: `skip_range` and the visibility walk both become
graph traversals rather than index arithmetic.

**A join as the sibling step immediately following its router** — the choice here — costs
one step type and one placement rule, and touches neither the executor's positional
model, nor the SSE format, nor the Gantt. All the remaining work lands in the document
schema and the canvas.

## 1. Document language

```python
class JoinSettings(DocSchema):
    mode: Literal["append"] = "append"


class JoinStep(StepBase):
    type: Literal["join"] = "join"
    settings: JoinSettings
```

`JoinStep` joins the `Step` union alongside `RouterStep`.

### Placement rules

Rule 1 of the router design — *a router must be the last step of its list* — is replaced
by a pair:

1. **A router may be followed only by a `join`.** Nothing else may sit after a router in
   the same list.
2. **A `join` may follow only a router.** It cannot open a list, and cannot follow an
   ordinary step.

Together these keep every other guarantee the router design relies on: a router still has
at most one successor, and that successor is the only place control can arrive from more
than one branch.

Consequences worth stating, because they are what the validator must actually reject:

- At most one join per router — rule 2 makes a second one unreachable, but the error
  message should say "this router already has a join" rather than "a join may follow only
  a router".
- A router with no join keeps the approved behaviour: its branches end the flow.
- A router nested inside a branch has its join inside that same branch. The depth limit of
  5 is unchanged and now bounds router/join pairs.
- Removing a router removes its join along with its subtree (§4).

## 2. Execution semantics

### Where the join sits in the walk

Pre-order over the tree already gives a router's subtree a contiguous index range. A join
is the next sibling, so it is the next index after that range:

```
index:  4  step        5  router   6  br_a/s1   7  br_a/s2   8  br_b/s1   9  join   10  step
              └─────────── router subtree, 5..8 ───────────┘
```

Nothing about `run_steps`, its `index` column, `skip_range(start, end)`, or the
`{stepId, index, status}` SSE payloads changes. The join is one more row, in its natural
position, and the Gantt draws it without modification.

### What the join does

It runs once, after every selected branch has finished, and succeeds with:

```json
{
  "branches": [
    {"id": "br_x", "name": "Urgent",  "output": {"text": "…"}},
    {"id": "br_y", "name": "Routine", "output": null}
  ],
  "by_id": {
    "br_x": {"text": "…"},
    "br_y": null
  }
}
```

- `branches` is ordered by the order the branches ran, which is document order.
- A branch's `output` is the output of the **last step that ran in it**.
- An **empty branch** that was selected contributes an entry with `output: null` — it was
  taken, it just had nothing to do.
- A branch **cut short by a `filter`** — one whose filter evaluated to `continue: false`,
  skipping the rest of that branch — is **absent from both fields**. A branch that merely
  *ends* with a filter that passed is not cut short: it contributes normally, with the
  filter's own `{"continue": true, "reason": …}` as its output. The router design
  already gives `filter` the meaning "this path stops here"; a path that stopped did not
  produce a result, and including a partial one would put complete and incomplete results
  in the same list with no way to tell them apart.
- **No branch selected** is not an error. The join succeeds with
  `{"branches": [], "by_id": {}}` and the flow continues.
- A step that **fails** inside a branch still fails the whole run, so the join never runs
  in that case.

`by_id` duplicates `branches` keyed by branch id. It exists because
`{{join_1.branches[0].output.text}}` is positional: adding a branch, or reordering one,
silently changes what index 0 means. `{{join_1.by_id.br_x.text}}` does not move. The
grammar already supports both forms — `REF_PATH_SOURCE`
(`apps/api/app/schemas/refs.py:16`) accepts `.name` and `[0]` segments.

### The executor

`run_steps` (`apps/api/app/services/executor.py:464`) is already becoming recursive in the
router design. On a `router` step it now collects, per selected branch, the output of the
last step it actually ran and whether a `filter` stopped it — the recursion returns that
instead of nothing — and hands the collected list to the `join` row that follows.

`skip_from` (`executor.py:421`) and `abort` (`executor.py:440`) need nothing beyond the
router design's changes: a join is an ordinary row at an ordinary index.

## 3. References and scope

The visibility rule from the router design §3 — *a step may reference exactly those steps
guaranteed to have run before it* — is already correct for a join and needs no new
concept. Two facts follow from it, and both must be tested:

- **A step after the join sees the join, and nothing inside any branch.** Branch contents
  never leaked out of a branch; that does not change because a join exists. So there are
  no "may not have run" references, no null-tolerant refs, and no default operator to add
  to the ref language.
- **A step inside a branch does not see the join**, which runs after it.

Implementation: the `visible: dict[str, int]` carried down the walk gains the join's id
when the walk leaves the router and moves to the next sibling. That is one line in the
same traversal.

The cross-branch error message the router design specifies ("`step_x` is in another branch
and may not have run") is exactly the message a post-join reference into a branch should
produce, and is the most likely mistake this feature invites.

### Static shape inference

`validation.py` infers output shapes per step type to catch a ref that resolves to the
wrong JSON shape before run time (`_AI_TEXT_OUTPUT_SCHEMA`,
`apps/api/app/services/documents/validation.py:112`). `join` gains:

```python
_JOIN_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "branches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "output": {},          # deliberately unconstrained
                },
            },
        },
        "by_id": {"type": "object"},       # deliberately unconstrained
    },
}
```

`output` and `by_id`'s values are left unconstrained on purpose: their shape depends on
which step ended each branch, which is per-branch and not knowable from the step type
alone. `_walk_schema` (`validation.py:185`) returns `None` for an unconstrained subtree,
which is already its "I don't know, don't complain" answer. Declaring anything narrower
would produce confident, wrong errors.

## 4. Operations

- **`AddStep` of a `join`** is accepted only at the index immediately following a router,
  in that router's list, and only if that router has no join yet. Every other placement is
  rejected with the rule that was broken.
- **`AddStep` of any other type** at the index following a router is rejected, as in the
  router design.
- **`RemoveStep` of a router** removes its join along with its subtree. Removing a router
  and leaving its join behind would produce a document that rule 2 rejects.
- **`RemoveStep` of a join** is allowed and leaves a valid document — the router's
  branches simply end the flow again. Any step that referenced the join becomes invalid
  and the existing validation reports it.
- **`MoveStep`** may not move a join; it has exactly one legal position. Moving a router
  moves its join with it.
- The four branch operations from the router design are unchanged.

## 5. Canvas and editor

The router design already replaces integer insertion indices with
`{branchId: string | null, index: number}` and emits nodes and edges for dagre to lay
out. The join adds:

- **Convergence edges.** Every branch's tail node draws an edge into the join node —
  every branch, not only the ones a given run would select, since selection is a run-time
  fact and the canvas is the document. dagre handles a node with several inbound edges
  without configuration; this is the shape it is built for.
- **The "+" after a router** exists only while that router has no join, and its picker
  offers only `join`. Once a join exists, the "+" moves to after the join, where it offers
  the full step list again.
- **An empty branch** still shows its own trailing "+", and its edge runs straight into
  the join.

## 6. Assistant

The system prompt (`apps/api/app/services/assistant_prompt.py`) gains the `join` step
type, its output shape including `by_id`, and the two rules it is most likely to break: a
router may be followed only by a join, and a step after a join may not reference anything
inside a branch. The self-correction loop handles the rest — validation errors already
feed back to it.

## 7. Testing

Backend (`docker compose exec -T api pytest -q tests`, one suite at a time — shared
`plumeai_test` DB):

- **schema:** join after a non-router rejected; join first in a list rejected; two joins on
  one router rejected; a step after a router that is not a join rejected; a router with no
  join still valid; a nested router with its own join valid at depth
- **operations:** adding a join only at the legal index; removing a router removes its
  join; removing a join leaves a valid document; moving a join rejected; moving a router
  carries its join
- **validation:** a reference from after the join into a branch rejected with the
  cross-branch message; a reference from inside a branch to the join rejected; a reference
  to `{{join_x.by_id.br_y}}` accepted; `_walk_schema` stays silent on `output`
- **executor:** several branches aggregated in document order; an empty selected branch
  yields `output: null`; a filter-stopped branch absent from both `branches` and `by_id`;
  no branch selected yields `{"branches": [], "by_id": {}}` and the flow continues; a
  failure inside a branch fails the run and the join never runs; pre-order index
  contiguity holds with a join present; cancel mid-branch

Frontend: `tsc` clean, plus the picker restriction and the convergence edges.

## 8. Risks

- **The join's output is the one place two branches meet.** Every other guarantee in the
  router design rests on branches never mixing. The `filter`-stopped-branch rule is what
  keeps that meeting honest — a partial result presented as a complete one would be a
  silent data bug, not a validation error. It is the first thing to test.
- **`by_id` and `branches` can drift.** They are two views of one list and must be built
  in one place in the executor, not assembled twice.
- **Canvas width.** Convergence pulls the layout back in rather than out, so the join
  reduces the horizontal growth the router design flags. Deep nesting is still bounded by
  the depth limit of 5.
- **Prompt surface.** The assistant now has a placement rule that is easy to state and
  easy to forget. If self-correction churns on it in practice, the fix is an example in
  the prompt, not a loosening of the rule.
