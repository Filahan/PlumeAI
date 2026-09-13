<p align="center">
  <img src="apps/web/public/logo.png" alt="PlumeAI" width="64" />
</p>

<h1 align="center">PlumeAI</h1>

<p align="center">
  Your private, self-hosted AI assistant. Chat with any LLM, automate tasks, connect to your services — all in one place.
</p>

<p align="center">
  <img src="docs/chat.jpg" alt="PlumeAI chat" />
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: ELv2" src="https://img.shields.io/badge/License-ELv2-3b82f6"></a>
  <img alt="Next.js" src="https://img.shields.io/badge/Next.js-16-000">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.115-009688">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12-3776ab">
  <img alt="PostgreSQL" src="https://img.shields.io/badge/Postgres-16-336791">
</p>

---

PlumeAI is a self-hosted alternative to ChatGPT/Claude. Bring your own keys (OpenAI, Anthropic, OpenRouter), use a tool-calling agent that talks to Gmail, Drive, Calendar, and Discord, design recurring **automations** through a guided interview, and track your token spend — all from a single `docker compose up`. Your data stays on your machine.

## Quick start

```bash
docker compose up -d
open http://localhost:3000
```

That's it. Add your provider key in Settings, configure integrations on the Tools page, start chatting.

For production, copy `.env.example` → `.env` and rotate `ENCRYPTION_KEY`. There is no login page: PlumeAI trusts whoever can reach it, so keep it on a private network or behind your own reverse-proxy auth.

## Features

- 🤖 **Chat** — Streaming responses, image attachments, conversation history with LLM-generated titles
- 🛠️ **Tool-using agent** — Web search, web fetch, arbitrary HTTP + native integrations
- 📧 **Integrations** — Gmail, Google Drive, Google Calendar, Discord. Credentials entered in-app, AES-GCM encrypted at rest
- ⚙️ **Automations** — A guided Q&A interview compiles your intent into a reusable skill that runs on schedule
- 📊 **Usage analytics** — Per-model token spend across 30m / 1h / 6h / 24h windows
- 🔒 **Private by design** — BYOK, no telemetry, no vendor lock-in, your conversations never leave your server

## Automations

Tell PlumeAI what you want. It asks the right follow-up questions, compiles your intent into a reusable skill, and runs it on demand or on a schedule.

<p align="center">
  <img src="docs/automations.jpg" alt="PlumeAI automations" />
</p>

## Stack

Next.js 16 · React 19 · Tailwind v4 · FastAPI 0.115 (Python 3.12) · SQLAlchemy 2.0 + Alembic · PostgreSQL 16 · nginx · Docker Compose

## Contributing

After cloning, wire up the secrets-blocking pre-commit hook (one-time):

```bash
git config core.hooksPath .githooks
```

See [`docs/security.md`](docs/security.md) for details on what's blocked and how to handle false positives.

## License

PlumeAI is licensed under the **[Elastic License 2.0 (ELv2)](LICENSE)** — a source-available license.
