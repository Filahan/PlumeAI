<img src="public/logo.png" alt="PlumeAI" width="64" />

# PlumeAI

Minimal BYOK chat UI for OpenAI, Anthropic and OpenRouter with usage analytics. Self-hosted via Docker.

## Quick start

```bash
docker compose up -d
open http://localhost:3000
# login with the default password: admin
```

That's it. Compose ships with safe-for-dev defaults baked in.

**Before exposing to the internet**, override the secrets:

```bash
cp .env.example .env
# Then edit .env — generate fresh values with:
#   AUTH_SECRET / ENCRYPTION_KEY   →  openssl rand -base64 32
#   ADMIN_PASSWORD_HASH            →  echo -n 'YourPassword' | shasum -a 256 | awk '{print $1}'
docker compose up -d
```

## Stack

Next.js 16, Tailwind v4, Drizzle ORM, Postgres 16, JWT cookie auth (`jose`), AES-GCM encryption for API keys at rest. LLM calls happen client-side — keys are decrypted on read and sent to the browser, never proxied.

## Local development

```bash
npm install
DATABASE_URL=postgres://plumeai:dev@localhost:5432/plumeai \
AUTH_SECRET=$(openssl rand -base64 32) \
ENCRYPTION_KEY=$(openssl rand -base64 32) \
ADMIN_PASSWORD_HASH=$(echo -n 'dev' | shasum -a 256 | awk '{print $1}') \
npm run dev
```

You still need a Postgres running locally (or `docker compose up -d db` for just the database).

Or in Docker with hot-reload:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

## License

MIT
