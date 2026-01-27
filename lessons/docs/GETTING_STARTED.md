# Getting Started

This guide will help you set up and run your first AI agent lesson.

## Prerequisites

- **Node.js 18+** - [Download here](https://nodejs.org/)
- **npm** (comes with Node.js)
- **Git** (for cloning the repository)

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/eren23/attocode.git
cd attocode/lessons
```

### 2. Install Dependencies

```bash
npm install
```

### 3. Configure Environment

```bash
cp .env.example .env
```

Add your OpenRouter API key to `.env`:
```bash
OPENROUTER_API_KEY=sk-or-xxxxxxxxxxxxx
```

Get your key at [openrouter.ai](https://openrouter.ai/). That's it - no SDK installation needed.

### 4. Verify Installation

Run the first lesson to verify everything works:

```bash
npm run lesson:1
```

You should see output showing the agent loop in action.

## Quick Start

### Running Lessons

Each lesson can be run individually:

```bash
npm run lesson:1   # Core loop basics
npm run lesson:2   # Provider abstraction
npm run lesson:3   # Tool system
# ... and so on through lesson:26
```

See [RUNNING.md](./RUNNING.md) for the complete lesson reference.

### Running Tests

```bash
# Run all tests
npm test

# Run tests for a specific lesson
npm run lesson:6   # Lesson 6 runs tests by design

# Run with UI
npm run test:ui
```

### Building

```bash
npm run build
```

This compiles TypeScript to the `dist/` directory.

## Project Structure

```
lessons/
├── 01-core-loop/             # Lesson 1: Agent loop basics
├── 02-provider-abstraction/  # Lesson 2: Multi-provider support
├── ...                       # Lessons 3-26
├── tricks/                   # Standalone utility modules
├── testing/                  # Test infrastructure
├── docs/                     # This documentation
├── package.json
└── tsconfig.json
```

Each lesson directory contains:
- `main.ts` - Entry point you can run
- `README.md` - Lesson explanation
- Supporting `.ts` files - Implementation modules
- `exercises/` - Practice exercises (where available)

## Learning Path

### Beginners (new to AI agents)

1. **Lessons 1-9** (Foundations) - Build core agent capabilities
2. **Lesson 18** (ReAct Pattern) - Structured reasoning
3. **Lessons 10-11** (Extensibility) - Hooks and plugins

### Intermediate (building production systems)

1. **Lessons 10-13** (Infrastructure) - Production patterns
2. **Lessons 19-22** (Operations) - Monitoring and safety
3. **Atomic Tricks** as needed

### Advanced (AI reasoning systems)

1. **Lessons 14-17** (Memory, Planning, Reflection, Multi-Agent)
2. Integrate with production infrastructure

## Milestone Checkpoints

The course is organized into milestones:

| Milestone | Lessons | Achievement |
|-----------|---------|-------------|
| **Agent Foundations** | 1-9 | Complete working agent with tools, streaming, testing |
| **Production Ready** | 10-13 | Extensible plugin system with API support |
| **AI Reasoning** | 14-18 | Memory, planning, reflection capabilities |
| **Operations** | 19-22 | Monitoring, sandboxing, human oversight |
| **Advanced** | 23-26 | Execution policies, production patterns, tracing |

## Troubleshooting

### "Cannot find module" errors

Make sure you've installed dependencies:
```bash
npm install
```

### API key errors

1. Verify your `.env` file exists and has valid keys
2. Check [PROVIDERS.md](./PROVIDERS.md) for correct variable names
3. Ensure you've installed the corresponding SDK

### TypeScript errors

Ensure you have TypeScript 5.3+:
```bash
npx tsc --version
```

### Permission denied

On Unix systems, you may need to make scripts executable:
```bash
chmod +x node_modules/.bin/*
```

## Next Steps

1. Start with [Lesson 1: Core Loop](../01-core-loop/README.md)
2. Configure your preferred [LLM provider](./PROVIDERS.md)
3. Try the exercises in each lesson
4. Build your own agent using these patterns!
