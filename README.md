# WebUI

A simple, clean chat interface for LLMs — inspired by Apple's minimal design language. Built with Next.js 15, TypeScript, Tailwind CSS, and shadcn/ui.

## Features

- **Multi-provider**: OpenAI, Anthropic, OpenRouter
- **Client-side**: API keys stored in localStorage, calls made directly from browser
- **Streaming**: Real-time token streaming for all providers
- **Markdown**: Rich text rendering with code blocks
- **Conversation history**: Persistent across sessions via localStorage
- **Collapsible sidebar**: Clean navigation with conversation list
- **Stop generation**: Abort ongoing requests instantly

## Getting Started

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Configuration

1. Open **Settings** from the sidebar
2. Select your provider and model
3. Paste your API key
4. Start chatting

Your API key is stored **locally** in your browser — it never hits our servers.

## Tech Stack

- Next.js 15 (App Router)
- TypeScript
- Tailwind CSS v4
- shadcn/ui
- Lucide icons

## License

MIT
# Plume
