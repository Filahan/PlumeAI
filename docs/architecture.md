# Architecture

This is a contributor-facing map of PlumeAI: what each service does, how an automation is
represented and executed, and where to look in the code for more detail. Facts here come from
reading `apps/api` and `apps/web` on branch `feat/automation-builder`; where something is likely to
drift, this doc points at the source file rather than restating it.

## Services

| Service | What it is | Where |
| --- | --- | --- |
| `web` | Next.js 16 (React 19) app, served by `next dev`/`next start` behind nginx | `apps/web` |
| `api` | FastAPI (Python 3.12) backend: REST + SSE, the executor, the scheduler | `apps/api` |
| `db` | PostgreSQL 16 | `docker-compose.yml` |
| `proxy` | nginx: routes `/api/*` to the backend, everything else to Next.js, buffering off for SSE | `nginx.conf` |

The scheduler and the run executor are **in-process** inside the `api` container — there is no
separate worker process or queue. `app/main.py`'s lifespan starts APScheduler and recovers any run
left `running`/`queued` by a previous process; on shutdown it cancels in-flight runs and closes
MCP connections.

## The automation document

An automation is stored as one JSON document: a `name`, a `model` (provider + model id), a
`trigger`, and an ordered list of `steps`. The schema lives in `app/schemas/documents.py` (Pydantic
v2, frozen models, snake_case throughout — this is a stored interchange format, not a per-endpoint
API shape). Here is the canonical example used across the test suite
(`apps/api/tests/conftest.py::EXAMPLE_DOCUMENT`):

```json
{
  "name": "Morning digest from my boss",
  "description": "Summarize unread emails from Dana and post the summary to Slack.",
  "model": { "provider": "openai", "model": "gpt-4o-mini" },
  "trigger": {
    "type": "schedule",
    "settings": { "mode": "cron", "cron": "0 8 * * 1-5", "timezone": "Europe/Paris" }
  },
  "steps": [
    {
      "id": "step_k3f9a",
      "name": "Find unread emails from Dana",
      "type": "action",
      "settings": {
        "integration": "gmail",
        "action": "gmail_search",
        "input": {
          "query": { "kind": "ai", "value": "Unread emails from dana@acme.com since yesterday" },
          "max_results": { "kind": "literal", "value": 20 }
        }
      },
      "retry": { "max_attempts": 3, "backoff_seconds": 10 },
      "timeout_seconds": 120,
      "valid": true
    },
    {
      "id": "step_p2m7c",
      "name": "Summarize the emails",
      "type": "ai",
      "settings": {
        "instructions": "Emails: {{step_k3f9a.output}}. Write a 5-bullet summary.",
        "tools": ["gmail_get"],
        "output": {
          "mode": "json",
          "schema": {
            "type": "object",
            "properties": { "summary": { "type": "string" }, "urgent": { "type": "boolean" } },
            "required": ["summary", "urgent"]
          }
        }
      },
      "valid": true
    },
    {
      "id": "step_q8d1e",
      "name": "Only continue if there was something",
      "type": "filter",
      "settings": {
        "mode": "rules",
        "rules": {
          "combinator": "and",
          "conditions": [
            {
              "left": { "kind": "ref", "value": "{{step_k3f9a.output.count}}" },
              "op": "gt",
              "right": { "kind": "literal", "value": 0 }
            }
          ]
        }
      },
      "valid": true
    },
    {
      "id": "step_z5r2b",
      "name": "Post to Slack",
      "type": "action",
      "settings": {
        "integration": "slack",
        "action": "slack_send_message",
        "input": {
          "channel": { "kind": "literal", "value": "#me" },
          "text": { "kind": "ref", "value": "{{step_p2m7c.output.summary}}" }
        }
      },
      "valid": true
    }
  ]
}
```

Key pieces of the language:

- **`FieldValue`** — every step input is `{kind: "literal" | "ref" | "ai", value: ...}`. `ref`
  values must match `{{ path }}` exactly (`app/schemas/refs.py:REF_FULLMATCH_RE`); `ai` values must
  be a non-empty instruction string. A `ref`/`ai` `FieldValue` is resolved at run time, never at
  save time.
- **Reference paths** (`app/services/refs.py`) — `step_x.output.a.b[0]` or `trigger.now` /
  `trigger.date` / `trigger.timezone`. Resolution only ever indexes into `dict`/`list` (never
  `getattr`), which is a deliberate security boundary against walking arbitrary Python object
  internals through a crafted path.
- **Step types** — `action` (`settings.integration` + `settings.action` + `input` map), `ai`
  (`settings.instructions`, `settings.tools` — a list of catalog action names it may call —
  `settings.output.mode` of `text` or `json` with a schema), `filter` (`settings.mode` of `rules`
  — a `Rules` tree of `Condition`s — or `ai` — a plain instruction).
- **Trigger** — `manual`, or `schedule` with `settings.mode` of `cron` (a cron string + optional
  timezone) or `interval` (`every_minutes`, 1–10080).
- **Validation** (`app/services/documents/validation.py`) — every document read is re-validated
  against the *live* catalog, so a step whose integration was since disconnected shows up as a
  fresh warning rather than a stale one baked in at save time. Issues carry a `path` (e.g.
  `steps[0].settings.input.query`) and a `level` of `error` or `warning`.

## Operations and versions

The document is never edited by sending a whole new document except from the JSON editor
(`PUT /automations/{id}`, which is the one write that rejects a document that doesn't
re-validate as `AutomationDocument`). Every other write — the canvas, the inspector, the assistant
— sends `Operation`s to `POST /automations/{id}/operations`:

- `add_step` (`step`, optional `index`)
- `update_step` (`step_id`, `patch`) — top-level keys in `patch` overwrite; `patch.settings`
  merges **one level deep** into the step's existing settings (so patching `input.query` alone
  requires resending the whole `input` map); `patch` may never include `id`.
- `remove_step` (`step_id`)
- `move_step` (`step_id`, `index`)
- `set_trigger` (`trigger`)
- `set_meta` (`name?`, `description?`, `model?`)

`app/services/documents/operations.py` applies these against a document immutably (documents are
frozen Pydantic models; every operation builds a new instance). A successful write that actually
changed the document creates a new row in `automation_versions`, numbered from 1, tagged with
`created_by` (`user`, `assistant`, `json`, `migration`, or `restore`). `automations.document` is
always the current draft and stays in sync with the latest version; `GET
/automations/{id}/versions/{number}` and `POST .../restore` read/roll back to any past one.
`app/services/documents/diff.py` renders a human-readable summary of what an operation batch or a
JSON save changed (used for the assistant's "Applied" list and the JSON editor's diff).

## The execution model

`app/services/executor.py` runs one `asyncio.Task` per run, in-process. `POST
/automations/{id}/runs` (and the scheduler, and the assistant's `run_test`) create a `queued` `Run`
row plus one `RunStep` per document step, commit, and hand the run id to
`executor.start_run_in_background`.

- **Concurrency** — up to `MAX_CONCURRENT_RUNS = 4` runs execute at once in the process (a
  semaphore); more than that simply wait in `queued`. A partial unique index
  (`runs_one_active_per_automation`, on `(automation_id) WHERE status IN ('queued','running')`)
  makes "one active run per automation" durable at the database level, backing up the
  application-level lock (`app/services/runs.py:creation_lock`) that a manual start and a schedule
  fire both take before creating a run.
- **Pinned version** — a run always executes the document of the version it was created against
  (`run.version_id`), never the live draft, so editing an automation mid-run doesn't change what's
  executing.
- **Per-step loop** — each step gets a `RetryPolicy` (from the step, or a per-type default: 3
  attempts/10s backoff for `action`, 2/10s for `ai`, 1/0s for `filter`) and a timeout (120s/300s/60s
  by default). Backoff doubles each attempt, capped at 120s. Only *retryable* failures get another
  attempt — a dangling `{{ref}}`, a schema the model can't satisfy, a tool that rejected the
  request outright (`PermanentStepFailure`), or a missing API key fail on the first attempt; a
  tool's `ok=False, retryable=True` result, an upstream provider blip, or a timeout get retried.
- **AI field fill** (`app/services/ai_fill.py`) — an action step's `ai`-kind inputs are resolved in
  one shared model call per step (not one per field), using the action's input schema, the
  automation's context, and prior step outputs.
- **AI step** — runs the tool-using agent loop (`app/agent/runner.py`) against the step's
  instructions (with `{{refs}}` interpolated) as the user turn, and automation context (name,
  today's date, prior outputs) as the system turn; text and tool activity stream out as run
  events. A `json`-mode output does one extra "reformat-only" model call to coerce the final
  answer into the declared schema.
- **Filter semantics** — `rules` mode evaluates deterministically
  (`app/services/filters.py:evaluate_rules`); `ai` mode asks the model a forced yes/no with a
  reason. A filter that decides "no" is not a run failure: the run marks every remaining step
  `skipped`, records `stopped_by_step_id`, and still finishes `succeeded`.
- **Cancellation** — `POST /automations/{id}/runs/{id}/cancel` calls `asyncio.Task.cancel()` on the
  run's task. The step in flight is marked `cancelled`, the rest `skipped`. Process shutdown
  cancels every in-flight run the same way; the next startup fails anything still
  `running`/`queued` from a prior process (`mark_orphaned_runs_failed`), since nothing survives a
  restart to finish it.
- **Redaction** — a step's `resolved_input` is masked by key name (`password`, `token`, `secret`,
  `key` substrings) before it's stored or emitted. Step **outputs** and traces are deliberately
  *not* redacted — a tool's response has no key names PlumeAI can trust to mean "secret", and the
  run detail view exists to show exactly what a run produced.
- **Run timeout** — a whole run is capped at 20 minutes as a backstop against a step that never
  returns.
- **History** — up to 200 past runs are kept per automation; older ones are pruned after each run
  finishes.

## Scheduling

`app/services/scheduler.py` wraps APScheduler's `AsyncIOScheduler`, one job per enabled automation
with a `schedule` trigger, keyed by automation id. The automations table is the source of truth:
`sync_job`/`remove_job` are called from every write that could change a schedule
(`save_document`, `set_enabled`, `delete_automation`), and `reload_all()` rebuilds the whole job
set from the table at startup — so a stale, empty, or lost jobstore costs nothing but the next
fire time. The jobstore is Postgres-backed (`SQLAlchemyJobStore`, via the sync `psycopg` driver
since APScheduler 3 is synchronous) with an in-memory fallback if that can't be opened; a
scheduler that fails to start never blocks the API from serving everything else. `coalesce=True`
and `max_instances=1` collapse a backlog of missed fires into one run and prevent a slow
automation on a short interval from stacking runs on itself; `create_run`'s active-run check
covers the case of a manual run colliding with a fire. A cron/interval trigger without its own
timezone falls back to the workspace timezone (Settings).

## Live progress (SSE)

`GET /automations/{id}/runs/{run_id}/events` is a Server-Sent Events stream, data-only, camelCase.
It always opens with a `snapshot` built from the database (so a late-connecting or reconnecting
client starts from authoritative state), then forwards whatever the in-process pub/sub
(`app/services/run_events.py`) publishes for that run id until a terminal `run_finished`. Event
types:

| Event | Meaning |
| --- | --- |
| `snapshot` | Full `RunDetail` as of connection time |
| `run_started` | Run moved to `running` |
| `step_started` | A step began an attempt |
| `step_retry` | An attempt failed and will retry, with the delay |
| `step_text` | A text delta from an `ai` step |
| `step_tool_call` / `step_tool_result` | Tool activity inside an `ai` step's agent loop |
| `step_finished` | A step reached a terminal status, with an output preview (and the full output if small enough) |
| `run_finished` | The run reached a terminal status; stream ends |

Queues are per-subscriber, bounded (1000 events), and drop the *oldest* event when full — a slow
client loses early progress rather than stalling the executor, and the initial DB snapshot means a
reconnect always resyncs correctly regardless.

## The catalog

`app/services/catalog.py:build_catalog` assembles, on every document read/validate/run: every
first-party integration with its live `connected` status (`GET /tools`), the always-on builtin
actions (web search, web fetch, HTTP), and every registered MCP server's *cached* tool listing —
never a live network call, so building a catalog never depends on a third-party server answering.
`GET /api/tools` returns this as `{integrations, builtinActions, mcpServers}`; the frontend fetches
it once per session (`useCatalog`) and every editor surface (step picker, inspector, AI tools
picker, the assistant's own system prompt) reads from it.

## The assistant loop

`app/services/assistant.py` + `app/services/assistant_prompt.py` implement the builder assistant
(`POST /automations/{id}/assistant`). Design:

1. The model is forced to call one tool, `propose_changes`, whose parameters schema
   (`ASSISTANT_REPLY_SCHEMA`) is *generated* from the same `Operation` union
   `apply_operations` accepts — the model cannot propose an edit the builder has no way to
   apply. The reply carries `intent` (`answer` | `edit`), `message`, `operations`, and `run_test`.
2. **Self-correction, once per turn.** If `apply_ops` rejects the whole batch (bad step id,
   out-of-range index, malformed operation), or the batch applies but leaves error-level
   validation issues, the problem is fed back to the model in a follow-up call
   (`MAX_CORRECTIONS = 1`). What reaches the client is a fixed sentence, never raw Pydantic text.
3. **Untrusted run output.** A run can record a web page or an email. Anything a run produced is
   fenced in `<untrusted_run_output>` markers inside a *user* message (not the system prompt), and
   summarized by shape (`describe_shape`) rather than pasted in full — the model sees the
   structure it needs to write a `{{ref}}` against, not arbitrary third-party text with the
   authority of an instruction.
4. **Test run.** When `run_test` is true and the turn's edits weren't rejected, the assistant
   starts a run the same way `POST /runs` does (same creation lock, same 409-becomes-a-note-instead-of-a-failure
   behavior when one is already in flight) and reports the run id back in the transcript.
5. The transcript (`automations.assistant_messages`, capped at 100 entries) is replayed on every
   turn up to `MAX_HISTORY_MESSAGES = 20` / `MAX_HISTORY_CHARS = 12000`; a turn whose operations
   were rejected is replayed with a fixed note rather than the rejection text verbatim.

## MCP integration

`app/mcp/manager.py:McpManager` is a connection pool keyed by server name, one instance per event
loop. Each connection owns its own asyncio task (the MCP SDK's transports are anyio context
managers whose task group must be entered and exited by the same task), serving jobs off a queue
until told to close. Key behaviors:

- **stdio** servers run as a subprocess of the API container with no sandbox — registering one is
  equivalent to running that command on the server. That's why registration is gated by
  `assert_stdio_allowed` / the `MCP_ALLOW_STDIO` setting (`app/config.py`): on by default when
  `APP_ENV` is a development value, off otherwise, refusing registration while off. The child's
  environment is limited to the SDK's allowlist (`HOME`, `LOGNAME`, `PATH`, `SHELL`, `TERM`,
  `USER`) plus the server's own declared `env`, so secrets like `ENCRYPTION_KEY` or
  `DATABASE_URL` never reach it. The image has no `npx`; `uvx <package>` works.
- **http** servers are checked with `assert_public_url` before every connection unless
  `allow_private_network` is set (opt-in per server, for a server the operator runs on their own
  network).
- Tool ids are `mcp__<server>__<tool>`; the catalog exposes them under integration
  `mcp:<server>`. The catalog and the tool registry read the **cached** listing
  (`mcp_servers.cached_tools`, refreshed by `POST /mcp/servers/{id}/refresh` or on
  create/update), never a live connection — so assembling a catalog or validating a document
  never depends on a third-party server being reachable.
- A dead connection is detected by transport-failure classification (`MCPError(CONNECTION_CLOSED)`,
  broken pipes, etc.) and one reconnect is attempted automatically before a call fails outward.

## Data model

Postgres tables relevant to automations (`app/db/models.py`):

| Table | Purpose |
| --- | --- |
| `automations` | Current draft `document` (JSONB), `enabled`, denormalized `valid` + `last_run_id`/`last_run_status`, the assistant transcript |
| `automation_versions` | Immutable numbered snapshots, `created_by` = `user`\|`assistant`\|`json`\|`migration`\|`restore` |
| `runs` | One row per execution, pinned to a version, with tokens/timing/status; a partial unique index enforces one active run per automation |
| `run_steps` | One row per document step per run, created up front as `pending`; carries `resolved_input` (redacted), `output`, `error`, `trace` |
| `mcp_servers` | Registered MCP servers; `config_enc` is AES-GCM encrypted, `cached_tools` is the last successful sync |
| `settings` | Singleton row: provider keys, OAuth/tool credentials (encrypted), workspace `timezone` |
| `conversations` / `messages` / `usage_entries` | Chat (unrelated to automations, pre-existing) |

## API endpoints

All under `/api` (nginx strips the prefix before it reaches FastAPI).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/automations` | List automations (summary rows) |
| POST | `/automations` | Create one (optionally seeded with a name/document) |
| POST | `/automations/validate` | Dry-run validate a document without persisting |
| GET | `/automations/{id}` | Full detail, re-validated against the live catalog |
| PUT | `/automations/{id}` | Replace the whole document (JSON editor's Save) |
| PATCH | `/automations/{id}` | Rename / enable / disable |
| DELETE | `/automations/{id}` | Delete |
| POST | `/automations/{id}/operations` | Apply one or more `Operation`s |
| POST | `/automations/{id}/assistant` | One assistant turn |
| DELETE | `/automations/{id}/assistant` | Clear the assistant transcript |
| GET | `/automations/{id}/versions` | List version numbers |
| GET | `/automations/{id}/versions/{n}` | One version's document |
| POST | `/automations/{id}/versions/{n}/restore` | Restore a past version as a new one |
| POST | `/automations/{id}/runs` | Start a run (`manual` or `test`); 409 if one is active |
| GET | `/automations/{id}/runs` | List runs (paginated by `createdAt` cursor) |
| GET | `/automations/{id}/runs/{id}` | One run's detail, including steps |
| POST | `/automations/{id}/runs/{id}/cancel` | Cancel a running run |
| GET | `/automations/{id}/runs/{id}/events` | SSE live progress |
| GET | `/tools` | The full catalog (integrations, builtins, MCP servers) |
| GET/POST | `/tools/{name}/oauth/start`, `/tools/{name}/oauth/callback` | OAuth handshake |
| GET | `/tools/discord/meta` | Discord bot name + invite URL |
| PUT/DELETE | `/tools/credentials/{namespace}` | Save/clear app-level credentials (Google, Slack, Discord, Notion) |
| POST | `/tools/{name}/disconnect` | Disconnect an integration |
| GET | `/mcp/servers` | List registered MCP servers |
| POST | `/mcp/servers` | Register one (syncs tools; a failed sync still returns 201) |
| PUT/PATCH | `/mcp/servers/{id}` | Update / enable-disable |
| POST | `/mcp/servers/{id}/refresh` | Re-sync its tool listing |
| DELETE | `/mcp/servers/{id}` | Unregister |
| POST | `/mcp/servers/test` | Try a config without saving it |
| GET/PUT | `/settings` | Provider keys, default model, timezone |
| GET/POST/PATCH/DELETE | `/conversations`, `/conversations/{id}/messages` | Chat (pre-existing) |
| POST | `/chat/stream` | Streaming chat completion (pre-existing) |
| GET | `/usage` | Token usage entries |
| GET | `/health` | Liveness probe |

See `apps/api/app/routers/*.py` for exact request/response shapes.

## Frontend structure

- **`lib/automations/types.ts`** — the shared vocabulary: the document types mirroring
  `app/schemas/documents.py` (snake_case, matching the wire format exactly), the camelCase API
  envelope types, and small pure helpers (`describeTrigger`, `stepLabel`, `documentsEqual`).
- **`lib/automations/store.ts`** — a single zustand store, the editor's source of truth. Two write
  paths: **Design mode** persists per-gesture through `applyOperations` (one user action = one
  operation = one version, no Save button); **JSON mode** edits the draft locally
  (`setDocument`, debounce-validated against the server) and persists explicitly via
  `saveDocument` (`PUT`, the one write that can 422 with issues). The live run subscription
  (SSE) is owned here too, torn down on navigation or run switch.
- **Canvas** (`components/automations/canvas/`) — built on `@xyflow/react` + `@dagrejs/dagre`.
  Deliberately *not* a freeform graph editor: the whole graph (trigger node, one node per step, a
  trailing "add" node) is recomputed from the document on every render and laid out top-to-bottom
  by dagre; nodes are never draggable, so the layout is always the single source of truth for an
  automation that is fundamentally a linear list.
- **Inspector** (`components/automations/inspector/`) — the right-hand panel for whatever's
  selected. `schema-form/` renders an action's `inputSchema` into a form; each field has a
  three-way mode toggle (**Value** / **From step** / **Ask AI**) mapping onto `FieldValue.kind`
  (`literal`/`ref`/`ai`). A "From step" reference is built with a picker
  (`reference-picker.tsx`) that reads field names from a catalog action's `outputSchema` when one
  exists, else from the shape of what the step returned in the automation's last run.
- **JSON editor** (`components/automations/json/`) — a CodeMirror JSON editor, seeded from the
  draft, parsed continuously (a bad parse shows an error and leaves the draft alone), applied
  explicitly via the header's Save.
- **Assistant** (`components/automations/assistant/`) — a chat-style drawer; each turn shows the
  model's reply, an "Applied" list of what changed (with Undo on the newest turn, back to the
  version before it), and a link to the test run it started if any.
- **Run stream** (`components/automations/runs/`, `lib/automations/run-stream.ts` folded into the
  store) — the run panel and per-step rows subscribe to narrow store selectors so a `step_text`
  delta arriving several times a second re-renders only what's watching that run, not the whole
  editor.

## Testing strategy

- **Unit tests** (`apps/api/tests/*.py`) — pure, no database: the document schema and operations
  (`test_documents.py`), reference resolution (`test_refs.py`), filter evaluation
  (`test_filters.py`), the assistant prompt (`test_assistant_prompt.py`), the MCP manager
  (`test_mcp_manager.py`), the catalog (`test_catalog.py`), structured output, AI field fill, and
  the individual integrations (Slack, Notion) against stubbed HTTP.
- **Integration tests** (`apps/api/tests/integration/`) — against a real Postgres, because
  versioning, cascades, the 409-on-active-run, and the JSONB round trip are exactly what a fake
  session would get wrong. They spin up a throwaway `plumeai_test` database (derived from
  `DATABASE_URL`), rebuild the schema from the SQLAlchemy models once per session (drop +
  recreate, not `create_all`, so a column added to a model after a stale prior run is never
  silently missed), and truncate every table between tests rather than rolling back a transaction
  (the API commits inside request handlers, which a wrapping transaction would undo). The
  executor and the scheduler are replaced with test doubles so `POST /runs` leaves an inspectable
  `queued` run instead of racing a real execution.
- **Run them:**
  ```bash
  docker compose exec -T api pytest -q tests
  ```
- **Frontend:** no test suite yet; typecheck with `docker compose exec web npx tsc --noEmit` and
  lint with `docker compose exec web npm run lint`.

## Migration strategy

On startup (`app/main.py` lifespan), `Base.metadata.create_all` creates any table that doesn't yet
exist — this is what makes a brand-new `docker compose up` usable with no manual migration step.
A small set of idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements then bring an
existing database's schema up to date (currently: `settings.tool_credentials`,
`settings.timezone`, `automations.valid`), followed by a one-time conversion of any legacy `tasks`
rows into automations (renaming the old table to `tasks_legacy` as the marker that it already
ran). Every one of these statements has a matching Alembic revision
(`0002_tool_credentials`, `0003_automations_v2`, `0004_mcp_servers`) for operators who run
`alembic upgrade` explicitly instead — both paths are idempotent and guarded the same way, so
whichever runs first wins and the other is a no-op. See `apps/api/alembic/versions/` for the
revision history.
