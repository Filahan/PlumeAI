<img src="apps/web/public/logo.png" alt="PlumeAI" width="64" />

# PlumeAI

Self-hosted assistant: BYOK chat (OpenAI · Anthropic · OpenRouter), tool-calling agent (`web_search`, `web_fetch`, `http`, Gmail), automations (Q&R interview → skill → scheduled run), usage analytics. Monorepo: **Next.js front · FastAPI backend · Postgres**.

## Quick start

```bash
docker compose up -d
open http://localhost:3000
# default password: admin
```

Compose ships with dev-safe secrets baked in. To expose to the internet, copy `.env.example` → `.env` and rotate them.

## Architecture

```
                       ┌──────────────────────────────────┐
   browser :3000 ──▶── │   nginx (reverse proxy)          │
                       │                                  │
                       │   /  /_next/* ─▶ web (Next.js)   │
                       │   /api/*       ─▶ api (FastAPI)  │
                       │   /docs        ─▶ api (Swagger)  │
                       └──────────────────────────────────┘
                                      │
                                      ▼
                              ┌──────────────┐
                              │ db (Postgres │
                              │  16 alpine)  │
                              └──────────────┘
```

| Service | Role | Image |
|---|---|---|
| `proxy` | nginx alpine, HTTP+WebSocket reverse proxy on `:3000` | ~61 MB |
| `web` | Next.js 16 (UI + hooks + fetch only — zero secrets, zero DB) | ~150 MB prod |
| `api` | FastAPI 0.115 (auth · LLM · agent loop · OAuth · DB) | ~460 MB |
| `db` | Postgres 16-alpine with persistent `pgdata` volume | ~272 MB |

## Endpoints (FastAPI, behind `/api/`)

| | |
|---|---|
| `POST /auth/login` `POST /auth/logout` `GET /auth/me` | JWT cookie session |
| `GET /settings` `PUT /settings` | provider keys (encrypted AES-GCM at rest) |
| `POST /chat/stream` (SSE) | conversational chat with tool calling |
| `GET /conversations` `POST` `PATCH /{id}` `DELETE /{id}` | chat history |
| `POST /conversations/{id}/messages` `PATCH /{id}/messages/{mid}` | append + update |
| `GET /automations` `POST` `PATCH /{id}` `DELETE /{id}` | tasks CRUD |
| `POST /automations/chat` | LLM-driven Q&R interview (JSON mode) + parallel title gen |
| `POST /automations/run` (SSE) | run the compiled skill with tool-using agent |
| `GET /tools/gmail/oauth/start` `GET /callback` | Gmail OAuth handshake |
| `POST /tools/{name}/disconnect` | clear a tool's stored credentials |
| `GET /usage` | usage entries (input/output tokens per call) |
| `GET /docs` `GET /openapi.json` | Swagger UI |

Direct access to FastAPI for debug: `http://localhost:8000/health`. Same paths as via proxy, just without the `/api/` prefix.

## Tools setup

Credentials are entered through the UI — open `/tools`, click a card, and paste the
required keys into the **Credentials** section of its modal. They are AES-GCM encrypted
at rest in the `settings.tool_credentials` table. No `.env` editing required.

**Google integrations (Gmail, Drive, Calendar)** share one OAuth client:

1. https://console.cloud.google.com/apis/credentials → **OAuth 2.0 Client ID** of type **Web application**.
2. Under **Authorized redirect URIs**, add (once for all Google tools):
   ```
   ${FRONTEND_URL}/api/tools/google/oauth/callback
   ```
   In dev: `http://localhost:3000/api/tools/google/oauth/callback`.
3. On `/tools`, click any Google card → Credentials section → paste Client ID + Secret → **Save & Connect**.
   Gmail, Drive, and Calendar all reuse the same credentials.

**Discord**: create a bot in the Developer Portal, paste its token in the Discord card's
Credentials section, then click **Invite to a Discord server** in the same modal.

If Google returns `redirect_uri_mismatch`, the URI in step 2 doesn't match the one the
API sends — the modal shows the exact value to register.

## Tools available to the agent

**Built-in (always on)**
- `web_search(query)` — DuckDuckGo HTML scrape, top 5 results
- `web_fetch(url)` — fetch + HTML→text, SSRF guard
- `http(method, url, headers?, body?)` — arbitrary verb, SSRF guard

**Integrations** — connect once via OAuth, then mention `@<name>` in your prompt
- `@gmail` — `gmail_search` · `gmail_get` · `gmail_send` · `gmail_modify` · `gmail_mark_read` · `gmail_trash`

Adding an integration is one folder under `apps/api/app/integrations/` implementing the `Integration` protocol (name, schemas, `is_configured`, `execute`). Registered in `app/integrations/registry.py`.

## Observability

- **Logs**: structured JSON via `structlog` (timestamp, level, event, `request_id`, `method`, `path`, `duration_ms`). Every request gets a UUID `request_id` propagated via contextvars.
- **Errors**: every response from `/api/*` that's a non-2xx is **RFC 7807 Problem Details** with `Content-Type: application/problem+json`. Includes `type`, `title`, `status`, `detail`, `instance`, `request_id`.
- **Tracing**: `request_id` is echoed back in the response headers (`X-Request-Id`) so the client can show it in error toasts for support.

```bash
docker compose logs -f api | jq            # pretty JSON stream
docker compose logs -f api | jq 'select(.level=="error")'   # only errors
```

## Local development

The whole stack runs in docker-compose with hot reload (both sides):
- `web` mounts `./apps/web` as a volume → Next.js HMR through nginx
- `api` mounts `./apps/api/app` → uvicorn `--reload`

```bash
docker compose up -d
# Edit any file under apps/web/src or apps/api/app — reload is automatic.
```

To run the FastAPI alone for unit work:

```bash
cd apps/api
uv sync                         # or: pip install -e .
DATABASE_URL=postgresql+asyncpg://plumeai:plumeai@localhost:5432/plumeai \
AUTH_SECRET=dev-secret-please-change-32-bytes-min-len \
ENCRYPTION_KEY=$(openssl rand -base64 32) \
ADMIN_PASSWORD_HASH=$(echo -n admin | shasum -a 256 | awk '{print $1}') \
uv run uvicorn app.main:app --reload
```

## Migrations

Schema is managed by Alembic. On a fresh DB, the baseline migration creates the 5 tables. The migration runs automatically on `api` startup:

```bash
docker compose exec api alembic upgrade head
docker compose exec api alembic revision --autogenerate -m "your change"
```

The current schema (`conversations`, `messages`, `settings`, `tasks`, `usage_entries`) is binary-compatible with the previous Drizzle-managed Postgres volume — existing data, encrypted API keys and OAuth tokens carry over without re-encryption.

## Environment

| Var | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | e.g. `postgresql+asyncpg://plumeai:pwd@db:5432/plumeai` |
| `AUTH_SECRET` | yes | JWT HS256 secret; 32+ bytes |
| `ENCRYPTION_KEY` | yes | base64 of exactly 32 bytes — AES-GCM master key |
| `ADMIN_PASSWORD_HASH` | yes | `sha256(password)` hex |
| `FRONTEND_URL` | optional | default `http://localhost:3000`; anchors OAuth callback URIs |
| `LOG_LEVEL` | optional | default `INFO` |
| `APP_ENV` | optional | `dev` or `prod`; affects cookie `Secure` flag |

Generate fresh secrets:

```bash
openssl rand -base64 32                            # AUTH_SECRET, ENCRYPTION_KEY
echo -n 'YourPassword' | shasum -a 256 | awk '{print $1}'   # ADMIN_PASSWORD_HASH
```

## Stack

**Front (`apps/web`)** — Next.js 16, React 19, Tailwind v4. Pure client: every cross-page side-effect happens via a typed `fetch` wrapper to `/api/*`. No DB, no JWT verification, no secrets.

**Back (`apps/api`)** — Python 3.12 + FastAPI + uvicorn (uvloop). SQLAlchemy 2.0 async + asyncpg, Alembic migrations. `cryptography` for AES-GCM, PyJWT for sessions. SDKs `openai`, `anthropic`, `google-genai`. SSE via `sse-starlette`. `structlog` for JSON logs.

**Reverse proxy** — nginx alpine. Streams SSE without buffering. Forwards `Upgrade` for the Next dev HMR websocket.

## License

MIT
