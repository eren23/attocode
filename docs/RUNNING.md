# Running Lessons

Quick reference for running all 26 lessons in the course.

## Prerequisites

Before running any lesson, install dependencies, `npm install`

---

## Part 1: Foundations (Lessons 1-9)

Build the core components of an AI agent.

| # | Lesson | Command | Description |
|---|--------|---------|-------------|
| 1 | Core Loop | `npm run lesson:1` | The fundamental agent loop pattern |
| 2 | Provider Abstraction | `npm run lesson:2` | Multi-provider support (Anthropic, OpenAI, Azure) |
| 3 | Tool System | `npm run lesson:3` | Tool registry with Zod validation |
| 4 | Streaming | `npm run lesson:4` | Real-time response streaming |
| 5 | Error Recovery | `npm run lesson:5` | Retry strategies and circuit breakers |
| 6 | Testing Agents | `npm run lesson:6` | Mock providers and deterministic testing |
| 7 | MCP Integration | `npm run lesson:7` | Model Context Protocol for extensibility |
| 8 | Cache Hitting | `npm run lesson:8` | Prompt caching for cost optimization |
| 9 | Complete Agent | `npm run lesson:9` | **MILESTONE: Full integration** |

### Milestone: Agent Foundations

After completing Lesson 9, you have a production-capable agent with:
- Multi-provider support
- Safe tool execution with validation
- Real-time streaming
- Comprehensive error handling
- Test coverage
- Extensibility via MCP
- Cost optimization via caching

---

## Part 2: Production Infrastructure (Lessons 10-13)

Build systems for production deployment.

| # | Lesson | Command | Description |
|---|--------|---------|-------------|
| 10 | Hook System | `npm run lesson:10` | Event bus and hook registration |
| 11 | Plugin System | `npm run lesson:11` | Modular plugin architecture |
| 12 | Rules System | `npm run lesson:12` | Dynamic configuration loading |
| 13 | Client/Server | `npm run lesson:13` | API architecture with sessions |

---

## Part 3: AI Reasoning (Lessons 14-18)

Add advanced reasoning capabilities.

| # | Lesson | Command | Description |
|---|--------|---------|-------------|
| 14 | Memory Systems | `npm run lesson:14` | Episodic and semantic memory |
| 15 | Planning | `npm run lesson:15` | Task decomposition and planning |
| 16 | Reflection | `npm run lesson:16` | Self-critique and improvement |
| 17 | Multi-Agent | `npm run lesson:17` | Agent coordination patterns |
| 18 | ReAct Pattern | `npm run lesson:18` | Structured reasoning + acting |

---

## Part 4: Operations (Lessons 19-22)

Production operations and safety.

| # | Lesson | Command | Description |
|---|--------|---------|-------------|
| 19 | Observability | `npm run lesson:19` | Tracing and metrics |
| 20 | Sandboxing | `npm run lesson:20` | Safe code execution |
| 21 | Human-in-Loop | `npm run lesson:21` | Approval workflows |
| 22 | Model Routing | `npm run lesson:22` | Intelligent model selection |

---

## Part 5: Advanced Patterns (Lessons 23-26)

Advanced production patterns and evaluation.

| # | Lesson | Command | Description |
|---|--------|---------|-------------|
| 23 | Execution Policies | `npm run lesson:23` | Policy-based execution control |
| 24 | Advanced Patterns | `npm run lesson:24` | Production integration patterns |
| 25 | Production Agent | `npm run lesson:25` | Full production deployment |
| 26 | Tracing & Evaluation | `npm run lesson:26` | Performance analysis and benchmarks |

---

## Running Tests

```bash
# Run all tests
npm test

# Run tests with UI
npm run test:ui

# Run lesson 6 specifically (it's test-based)
npm run lesson:6
```

---

## Running Exercises

Each lesson includes exercises to practice the concepts:

```bash
# Run exercise tests for a specific lesson
npm run test:lesson:1:exercise

# Run all exercise tests
npm run test:exercises

# Verify all exercises and solutions
npm run verify:exercises
```

---

## Development Commands

```bash
# Build TypeScript
npm run build

# Watch mode for development
npm run dev

# Start the main entry point
npm start
```

---

## Using Different Models

Set the appropriate environment variable to use a specific models:

```bash
export OPENROUTER_API_KEY=sk-or-xxxxxxxxxxxxx
export OPENROUTER_MODEL=z-ai/glm-4.7
npm run lesson:1
```

---

## Running Without API Keys

Many lessons work with mock providers for testing:

```bash
# Lesson 6 uses mocks by default
npm run lesson:6

# Or modify any lesson to use ScriptedLLMProvider
```

See [PROVIDERS.md](./PROVIDERS.md) for mock provider setup.

---

## Quick Start Commands

```bash
# First time setup
npm install && cp .env.example .env

# Edit .env with your API key, then:
npm run lesson:1  # Start learning!
```

---

## Lesson Dependencies

While lessons can be run independently, some build on previous concepts:

```
Lesson 1 (Core Loop)
    └── Lesson 2 (Providers)
        └── Lesson 3 (Tools)
            └── Lesson 4 (Streaming)
                └── Lesson 5 (Errors)
                    └── Lesson 6 (Testing)
                        └── Lessons 7-8 (MCP, Caching)
                            └── Lesson 9 (Complete Agent) ← MILESTONE

Lesson 9 (Complete Agent)
    ├── Lessons 10-13 (Infrastructure)
    ├── Lessons 14-18 (AI Reasoning)
    └── Lessons 19-22 (Operations)
        └── Lessons 23-26 (Advanced)
```

---

## Getting Help

- Each lesson has its own `README.md` with detailed explanations
- See [GETTING_STARTED.md](./GETTING_STARTED.md) for setup help
- See [PROVIDERS.md](./PROVIDERS.md) for API configuration
