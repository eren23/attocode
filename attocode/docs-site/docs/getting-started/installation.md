---
sidebar_position: 1
title: Installation
---

# Installation

This guide walks you through setting up Attocode on your machine.

## Prerequisites

- **Node.js 20+** is required. On macOS, the recommended approach is Homebrew:

```bash
brew install node@20
```

Verify your Node.js version:

```bash
node --version
# Should output v20.x.x or higher

which node
# Recommended: /opt/homebrew/opt/node@20/bin/node
```

If your shell picks up an older version, prepend the Homebrew path:

```bash
export PATH="/opt/homebrew/opt/node@20/bin:$PATH"
```

- **Git** for cloning the repository.
- An API key for at least one LLM provider (see [Environment Setup](#environment-setup) below).

## Clone and Install

```bash
git clone https://github.com/eren23/attocode.git
cd attocode
npm install
```

Attocode declares `@anthropic-ai/sdk` and `openai` as optional peer dependencies. Install the SDK for the provider you plan to use:

```bash
# For Anthropic (direct API)
npm install @anthropic-ai/sdk

# For OpenAI (direct API)
npm install openai

# For OpenRouter, the openai SDK is used under the hood
npm install openai
```

## Environment Setup

Attocode needs an API key for at least one LLM provider. Create a `.env` file in the project root or export the variables in your shell:

```bash
# Option 1: OpenRouter (recommended - access to multiple models)
export OPENROUTER_API_KEY="sk-or-..."

# Option 2: Anthropic direct
export ANTHROPIC_API_KEY="sk-ant-..."

# Option 3: OpenAI direct
export OPENAI_API_KEY="sk-..."
```

You can also place these in a `.env` file at the project root. Attocode loads it automatically via `dotenv`.

Provider auto-detection checks keys in this order: **OpenRouter > Anthropic > OpenAI**. The first configured provider wins. You can override this at runtime with `--model` (see the [CLI Reference](./cli-reference.md)).

## Verify Installation

Run the help command to confirm everything works:

```bash
npx tsx src/main.ts --help
```

You should see the Attocode help banner listing all available options and commands.

## Building

Attocode is an ESM project (`"type": "module"` in `package.json`) written in TypeScript with strict mode enabled, targeting ES2022.

To compile TypeScript to JavaScript:

```bash
npm run build
```

This runs `tsc` and produces output in the `dist/` directory. The built entry point is:

```bash
node dist/src/main.js
```

## Project Structure at a Glance

```
attocode/
├── src/                # TypeScript source
│   ├── main.ts         # Entry point
│   ├── agent.ts        # Core orchestrator
│   ├── providers/      # LLM provider adapters
│   ├── tools/          # Tool implementations
│   └── integrations/   # Feature modules
├── dist/               # Compiled output (after build)
├── tests/              # Test suite (Vitest)
├── tools/              # Developer tooling (dashboard, eval)
├── package.json        # ESM, strict TypeScript, ES2022
└── tsconfig.json       # Compiler configuration
```

## Next Steps

With installation complete, head to the [Quick Start](./quick-start.md) guide to run your first session.
