<p align="center">
  <img src="apps/web/public/logo.png" alt="PlumeAI" width="64" />
</p>

<h1 align="center">PlumeAI</h1>

<p align="center">
  A self-hosted, source-available AI automation builder for non-technical people —
  an open alternative to Make, n8n and Zapier with AI at the core.
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: ELv2" src="https://img.shields.io/badge/License-ELv2-3b82f6"></a>
  <img alt="Next.js" src="https://img.shields.io/badge/Next.js-16-000">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.115-009688">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12-3776ab">
  <img alt="PostgreSQL" src="https://img.shields.io/badge/Postgres-16-336791">
</p>

---

PlumeAI lets you describe an automation in plain language — "every weekday at 8, summarize unread
emails from my boss and post it to Slack" — and it builds the trigger and the steps for you. You
can then edit anything it made on a visual canvas, connect the tools it needs (Gmail, Slack,
Notion, your own MCP servers, and more), and watch each run step by step. Everything runs on your
own machine with `docker compose up`: your keys, your data, your infrastructure.

> **Screenshots coming soon.** The automation builder replaces PlumeAI's earlier chat-first UI, so
> the previous screenshots in this repo no longer reflect the product. New ones will land here
> once the interface settles.

## Quick start

```bash
cp .env.example .env
docker compose up -d
open http://localhost:3001
```

Then, in the app:

1. **Add a provider key.** Open Settings and paste an OpenAI or Anthropic API key — PlumeAI is
   bring-your-own-key, there's no built-in model access.
2. **Connect a tool.** Go to Tools and connect whichever accounts your automation needs (Gmail,
   Slack, Notion, Discord, Google Drive/Calendar, or an MCP server). Each card walks you through
   getting the credentials.
3. **Build your first automation.** From the home screen, describe what you want in a sentence.
   The assistant drafts the trigger and steps, and you can refine anything it made on the canvas.

There is no login: PlumeAI trusts whoever can reach it, so keep it on a private network or put it
behind your own reverse-proxy authentication if you expose it further.

For anything beyond local testing, rotate `ENCRYPTION_KEY` in `.env` before deploying — see
[Configuration](#configuration).

## What you can build

Some concrete examples of what an automation looks like in practice:

- **Morning digest.** Every weekday at 8am, search Gmail for unread messages from your manager,
  have the AI summarize them into a few bullet points, and post the summary to a Slack channel.
- **Conditional web digest.** Every morning, search the web for news on a topic, and only continue
  (and email yourself a digest) if the AI decides the results are actually worth reading —
  otherwise the run stops quietly at the filter step.
- **Notion meeting log.** On a schedule, pull today's Google Calendar events, ask the AI to write a
  one-paragraph agenda from them, and create a new Notion page under a "Meetings" database with
  that agenda.

## How it works

An **automation** is one **trigger** followed by a linear list of **steps** — no branches, no
loops. Steps run top to bottom, and each one can use what an earlier step produced.

- **Trigger** — manual ("when I press Run"), an interval ("every N minutes"), or a schedule (a
  cron expression with a timezone, offered through presets: hourly, daily, weekdays, weekly, or a
  custom cron string).
- **Steps** — three kinds:
  - **action** — calls one action of one connected tool (search Gmail, post to Slack, call an MCP
    tool, make an arbitrary HTTP request).
  - **ai** — asks a model to do something described in natural language (summarize, draft,
    classify) and returns plain text or a JSON object shaped by a schema you define.
  - **filter** — stops the run here unless a condition holds. A filter can be a set of rules
    (compare a value to another with `=`, `≠`, `>`, `contains`, `is empty`, …) or a plain-language
    instruction the AI judges at run time.
- **Field modes** — every input field of an action step is filled one of three ways:
  - **Value** — you type it in directly.
  - **From step** — a reference to an earlier step's output (`{{step_id.output.path}}`), picked
    visually or typed by hand.
  - **Ask AI** — a natural-language instruction ("the summary from the previous step") that a
    model resolves into the actual value the moment the automation runs.
- **Versions** — every edit (yours, the assistant's, or a JSON save) creates a new numbered
  version of the document. You can view and restore any past version.
- **Runs** — starting an automation (manually, on a test, or on schedule) creates a run pinned to
  the document version it started from. You watch it live — each step's status, resolved input,
  output, and any tool calls it made — and every past run stays in the run history.

The assistant that builds and edits automations for you works the same way a human editing the
canvas does: it never writes to the document directly, it emits the same operations (add a step,
update a step, set the trigger, …) that the canvas itself uses, so nothing it does can produce a
document the builder couldn't also produce.

For the full detail — the document format, the execution model, retries, the assistant's
self-correction loop — see [`docs/architecture.md`](docs/architecture.md). For a plain-language
walkthrough of building automations in the UI, see [`docs/automations.md`](docs/automations.md).

## Connectors

PlumeAI ships with these first-party connectors, plus built-in web search, web fetch, and raw
HTTP actions available with no setup. Full action-by-action detail (inputs and outputs) is in
[`docs/connectors.md`](docs/connectors.md).

| Connector | Auth | What you can do |
| --- | --- | --- |
| Gmail | Google OAuth | Search, read, send, label, mark read/unread, trash messages |
| Google Drive | Google OAuth (shared client) | Search, read, list, create Google Docs, trash files |
| Google Calendar | Google OAuth (shared client) | List, read, create, update, delete events |
| Slack | Bot token (`xoxb-…`) | List channels, send messages (with threading), read channel history |
| Discord | Bot token | List servers/channels, read messages, send messages |
| Notion | Internal integration secret | Search, read pages, create pages, append content, query databases |
| Built-in | none | Web search, web page fetch, arbitrary HTTP requests |

Gmail, Drive and Calendar share one Google OAuth client — set it up once in Settings → Tools and
every Google connector uses it.

## Extending with MCP

Beyond the first-party connectors, PlumeAI can talk to any [Model Context Protocol](https://modelcontextprotocol.io)
server. Add one from the Tools page, and its tools show up in the step picker and the AI step's
tool list exactly like a first-party action, under the integration name `mcp:<your-server-name>`.

Two transports are supported:

- **stdio** — a command PlumeAI runs as a subprocess of the API container. There's no `npx` in
  the image, but `uv`/`uvx` are available, so most Python-based MCP servers work out of the box:

  ```
  Command:   uvx
  Arguments: mcp-server-time
             --local-timezone=Europe/Paris
  ```

  Registering a stdio server is equivalent to running that command inside the API container —
  there is no sandbox — so it's gated by `MCP_ALLOW_STDIO` (see [Configuration](#configuration)):
  on by default in development, off by default anywhere else, and registration is refused while
  it's off.

- **http** — a Streamable HTTP MCP server reached over the network, with optional headers (a
  bearer token, for instance). Not gated by `MCP_ALLOW_STDIO` — it's just an outbound request,
  guarded the same way `web_fetch`/`http` are (see below).

**Security note.** An HTTP server's URL is checked against private/loopback address ranges before
every connection unless you tick "Allow private network," which is meant only for a server you run
yourself on your own machine or network. See [`docs/security.md`](docs/security.md) for the full
threat model.

## Architecture

Next.js 16 (React 19) for the frontend, FastAPI (Python 3.12) for the backend, PostgreSQL for
storage, APScheduler running in-process inside the API for schedules, and nginx as the reverse
proxy tying it all together — one `docker compose up`, no external services required.

For the full breakdown of services, the automation document format, the execution model, and the
data model, see [`docs/architecture.md`](docs/architecture.md).

## Configuration

Copy `.env.example` to `.env` and adjust as needed:

| Variable | Meaning |
| --- | --- |
| `DB_PASSWORD` | Postgres password for the `plumeai` user/database. Change it for anything beyond local dev. |
| `ENCRYPTION_KEY` | Base64 of 32 random bytes, used to AES-GCM encrypt provider keys, OAuth tokens, and tool credentials at rest. **Generate a fresh one** with `openssl rand -base64 32` before deploying anywhere reachable from the internet — the shipped default is dev-only and public. |
| `FRONTEND_URL` | The public URL the app is served from. OAuth callback URIs are anchored on this, so it must match wherever you actually reach the app (e.g. `https://plumeai.example.com` in production). |
| `LOG_LEVEL` | API log verbosity (`INFO` by default). |
| `APP_ENV` | `dev` by default; also decides the default for `MCP_ALLOW_STDIO` below. |
| `MCP_ALLOW_STDIO` | Whether a `stdio` MCP server may be registered (it runs as a subprocess of the API container with no sandbox). Unset, it follows `APP_ENV`: on for `dev`/`development`/`local`/`test`, off otherwise. Set explicitly (`true`/`false`) to override. `http` MCP servers are unaffected. |

Everything else — provider API keys, OAuth credentials, bot tokens, MCP server configs, workspace
timezone — is configured at runtime from inside the app (Settings and Tools), not through
environment variables. Credentials are AES-GCM encrypted before they reach the database.

**Providers.** PlumeAI is bring-your-own-key. Automations (and the assistant that builds them)
currently pick a model from OpenAI or Anthropic. Add a key under Settings, and it becomes
available to pick as an automation's model and in the model dropdown elsewhere.

**Timezone.** The workspace has one IANA timezone (Settings → Timezone), used for any schedule
trigger that doesn't set its own timezone, and for what "today" and "now" mean inside a run
(`{{trigger.date}}`, relative dates, etc). A schedule trigger can also carry its own timezone,
independent of the workspace default.

**Upgrading.** This release drops the `conversations` and `messages` tables (the old chat-first
UI's transcripts) on first startup, and that migration cannot be reversed. If you have data in
those tables you want to keep, back up your database before upgrading.

## Development

**Run the backend tests:**

```bash
docker compose exec -T api pytest -q tests
```

Unit tests (`apps/api/tests/*.py`) are pure — no database. Integration tests
(`apps/api/tests/integration/`) spin up a throwaway `plumeai_test` database next to the dev one,
rebuild the schema from the SQLAlchemy models, and truncate tables between tests.

**Typecheck the frontend:**

```bash
docker compose exec web npx tsc --noEmit
docker compose exec web npm run lint
```

**Project layout:**

```
apps/api/app/
  routers/       FastAPI route handlers, one module per API area
  schemas/       Pydantic request/response and document schemas
  services/      Business logic — executor, scheduler, assistant, catalog, documents/…
  integrations/  First-party connectors (gmail, drive, calendar, discord, slack, notion)
  mcp/           MCP client (manager, schemas)
  tools/         Tool registry + builtin actions (web search/fetch, http)
  agent/         The tool-using agent loop shared by the assistant drawer and AI steps
  llm/           Provider clients (OpenAI, Anthropic) + structured output
  alembic/       Schema migrations

apps/web/src/
  app/                        Next.js App Router pages
  components/automations/     Canvas, inspector, step picker, assistant, runs, JSON editor
  components/tools/           Tools/connectors settings UI, MCP server management
  lib/automations/            Shared types + the automation editor's zustand store
  lib/api/                    Typed fetch wrappers for every backend endpoint
```

See [`docs/architecture.md`](docs/architecture.md) for what each of these actually does.

## License

PlumeAI is licensed under the **[Elastic License 2.0 (ELv2)](LICENSE)** — source-available, not
OSI-approved open source. In short: you can use, copy, modify, and self-host PlumeAI freely,
including commercially and including modified versions, as long as you don't offer it (or a
substantial part of its functionality) to third parties as a hosted or managed service, and you
keep the license notices intact. Read the full text in [`LICENSE`](LICENSE) before relying on it
for a specific use case.

## Contributing / roadmap

Contributions are welcome. Wire up the secrets-blocking pre-commit hook once per clone before your
first commit:

```bash
git config core.hooksPath .githooks
```

See [`docs/security.md`](docs/security.md) for what it blocks and how to handle a false positive.

Known directions for future work, not yet built:

- Webhook and other event-based triggers (today: manual, interval, and cron/schedule only)
- Branching (today an automation is strictly linear — a filter can only stop a run, not fork it)
- More first-party connectors
- Multi-user support (today PlumeAI is single-user with no login)
