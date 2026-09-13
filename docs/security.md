# Security

## Pre-commit hook (one-time setup)

The repo ships a pre-commit hook that blocks commits containing secrets,
`.env` files, and sensitive credential formats. Wire it up once per clone:

```bash
git config core.hooksPath .githooks
chmod +x .githooks/pre-commit
```

After that, every `git commit` runs through the hook automatically. To allow a
detected false positive, append `# pragma: allowlist secret` on the same line:

```python
# This is a fake key used in tests, not a real one:
test_key = "sk-test123456789012345678901234567890"  # pragma: allowlist secret
```

### What the hook blocks

| Category | Pattern / Rule |
| --- | --- |
| `.env` files | Any `.env`, `.env.local`, `.env.production`, etc. — except `.env.example` |
| Key / cert files | `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.jks`, `*.keystore` |
| OpenAI API key | `sk-[A-Za-z0-9_-]{20,}` |
| Anthropic API key | `sk-ant-[A-Za-z0-9_-]{20,}` |
| Google OAuth secret | `GOCSPX-[A-Za-z0-9_-]{20,}` |
| Google API key | `AIza[0-9A-Za-z_-]{35}` |
| AWS access key | `AKIA[0-9A-Z]{16}` |
| Discord bot token | `M…{23}.…{6}.…{27}` triple-segment |
| PEM private key | `-----BEGIN … PRIVATE KEY-----` |
| Slack token | `xox[abprs]-…` |
| GitHub PAT | `ghp_…{36}` |
| Stripe live secret | `sk_live_…{24}` |

## Threat model (current baseline)

PlumeAI is a **single-tenant, self-hosted** assistant. It is not designed for multi-tenant
SaaS hosting. Its threat model focuses on:

- Operator credentials at rest (provider keys, OAuth tokens, bot tokens) — encrypted AES-GCM with `ENCRYPTION_KEY`.
- No built-in login. The app is single-user and trusts the network: expose it only on a private network or behind reverse-proxy authentication.
- SSRF — `app/tools/base.py:assert_public_url` blocks private/loopback/link-local before any user-controlled fetch. Registered `http` MCP servers go through it too, unless the server opts into `allowPrivateNetwork`.
- OAuth CSRF — random `state` cookie verified on callback (Google integrations).
- Command execution via MCP — a `stdio` MCP server is a command the API container runs as a subprocess. With no built-in login, registering one is equivalent to arbitrary code execution inside the container, so it is gated behind `MCP_ALLOW_STDIO` (see the finding below).

## Findings from the security audit (2026-06-04)

| # | Severity | Area | Finding | Status |
| --- | --- | --- | --- | --- |
| 1 | — | Auth | Admin password hashed with raw SHA-256 (no salt, no work factor). | Closed — the password login was removed entirely (2026-09-13). Access control is delegated to the network / reverse proxy. |
| 2 | Low | Docker compose | `docker-compose.yml` provides a dev-safe fallback for `ENCRYPTION_KEY`. | Acceptable — documented in `.env.example`. Production deployments must override via `.env`. |
| 3 | Info | Error handling | Unhandled errors log full stack traces server-side but expose only a generic message + `request_id` to the client. | OK |
| 4 | — | Cookies | Session cookie hardening. | N/A — no session cookie since the login removal. |
| 5 | Info | SSRF | All user-controlled URLs (`web_fetch`, `http`) pass through `assert_public_url`. | OK |
| 6 | Info | XSS | Markdown rendered with `react-markdown` defaults — raw HTML disabled, no `dangerouslySetInnerHTML`. | OK |
| 7 | Info | CORS | No `CORSMiddleware` configured — frontend served behind the same nginx, same-origin requests only. | OK for the current architecture. Add strict CORS if exposing the API cross-origin. |
| 8 | Info | OAuth | Unified Google callback `/api/tools/google/oauth/callback`, random `state` cookie verified, redirect URI anchored on `FRONTEND_URL`. | OK |
| 9 | Info | Crypto | AES-GCM 256-bit, 12-byte random IV, format binary-compatible with Node Web Crypto. | OK |
| 10 | Info | Secrets in repo | No real secrets found in tracked files or git history. Only placeholders (`GOCSPX-...`, `apps.googleusercontent.com` as documentation). | OK |
| 11 | High | MCP (stdio) | `POST /mcp/servers` with `transport: "stdio"` runs an arbitrary command inside the API container (`app/mcp/manager.py`). The API has no login, so anyone who can reach it can execute code as the API user. | Mitigated — gated behind `MCP_ALLOW_STDIO`, which defaults to on only when `APP_ENV` is a development value and off otherwise; registration is refused (`403`-style `Forbidden`) when disabled. The child process gets only the SDK's environment allowlist (`HOME`, `LOGNAME`, `PATH`, `SHELL`, `TERM`, `USER`) plus the server's own `env`, so `ENCRYPTION_KEY` / `DATABASE_URL` / provider keys are not inherited. Deployments reachable from an untrusted network must leave it off. |
| 12 | Info | MCP (http) | A registered Streamable HTTP MCP server is an outbound request to a user-supplied URL. | OK — `assert_public_url` runs before every connection; `allowPrivateNetwork` is a deliberate per-server opt-out for servers on the operator's own machine. |
| 13 | Info | MCP (secrets) | A server's connection config (`env` values for stdio, `headers` for http) can carry API tokens. | OK — stored AES-GCM encrypted in `mcp_servers.config_enc`; the API only ever returns the *names* of those entries, masks secret-looking argv values and URL query strings, and strips query strings from stored errors. |

## Recommended next steps (out of scope of this PR)

- If the deployment must be reachable from an untrusted network, put an authenticating reverse proxy (e.g. Authelia, oauth2-proxy, Cloudflare Access) in front of nginx. `app/auth.py:get_current_user` is the single hook point if an in-app auth layer is ever reintroduced.

## Reporting a vulnerability

If you find a security issue, please report it
