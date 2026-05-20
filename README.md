# PlumeAI

Minimal BYOK chat UI for OpenAI, Anthropic and OpenRouter with usage analytics. Self-hosted via Docker.

## Quick start

```bash
cp .env.example .env
# fill in DB_PASSWORD, AUTH_SECRET, ENCRYPTION_KEY, ADMIN_PASSWORD_HASH (see below)
docker compose up -d
open http://localhost:3000
```

Generate secrets:

```bash
# AUTH_SECRET and ENCRYPTION_KEY (32 random bytes, base64)
openssl rand -base64 32

# ADMIN_PASSWORD_HASH (SHA-256 hex of your admin password)
echo -n 'YourStrongPassword' | shasum -a 256 | awk '{print $1}'
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

## License

MIT
