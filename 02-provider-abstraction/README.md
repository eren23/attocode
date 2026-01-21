# Lesson 2: Provider Abstraction

## What You'll Learn

Real-world agents need to work with multiple LLM providers:
- **Anthropic** (Claude) - Great for coding tasks
- **OpenAI** (GPT-4) - Widely used, good general purpose
- **Azure OpenAI** - Enterprise compliance, same models
- **Local models** - Privacy, cost control

In this lesson, we'll build a provider abstraction that:
1. Defines a common interface
2. Auto-detects available providers
3. Allows runtime switching

## Key Concepts

### Why Abstract Providers?

Without abstraction, your code becomes:
```typescript
// ❌ Tightly coupled to one provider
import Anthropic from '@anthropic-ai/sdk';
const client = new Anthropic();
const response = await client.messages.create({ ... });
```

With abstraction:
```typescript
// ✅ Works with any provider
const provider = getProvider(); // Auto-detects from env
const response = await provider.chat(messages);
```

### The Provider Interface

Every provider must implement:
```typescript
interface LLMProvider {
  readonly name: string;
  chat(messages: Message[], options?: ChatOptions): Promise<ChatResponse>;
}
```

This simple contract enables:
- **Swappable implementations**: Change providers without changing agent code
- **Testing**: Use mock providers in tests
- **Fallbacks**: Try provider A, fall back to provider B

### Environment-Based Detection

We detect providers from environment variables:
- `ANTHROPIC_API_KEY` → Anthropic Claude
- `OPENAI_API_KEY` → OpenAI
- `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_ENDPOINT` → Azure OpenAI

## Files in This Lesson

- `types.ts` - Extended types for multi-provider support
- `provider.ts` - Base provider interface and factory
- `adapters/anthropic.ts` - Anthropic Claude adapter
- `adapters/openai.ts` - OpenAI adapter
- `adapters/azure.ts` - Azure OpenAI adapter
- `adapters/mock.ts` - Mock provider for testing
- `main.ts` - Demo with provider auto-detection

## Running This Lesson

```bash
# Set at least one API key
export ANTHROPIC_API_KEY=your-key-here
# OR
export OPENAI_API_KEY=your-key-here

# Run the demo
npm run lesson:2
```

## Adapter Pattern

Each adapter translates our interface to the provider's SDK:

```
Our Interface          Provider SDK
    ↓                      ↓
  Message[]    →     Anthropic format
  Message[]    →     OpenAI format
  Message[]    →     Azure format
```

This is the **Adapter Pattern** - a classic design pattern for making incompatible interfaces work together.

## Next Steps

After completing this lesson, move on to:
- **Lesson 3**: Tool System - Build a proper tool registry with validation
