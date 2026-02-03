# Contributing to Attocode

## Development Setup

### Prerequisites

- Node.js 20+ (check with `node --version`)
- npm 9+ (check with `npm --version`)

### Getting Started

```bash
# Clone the repository
git clone https://github.com/eren23/attocode.git
cd attocode

# Install dependencies
npm install

# Build the project
npm run build

# Run tests
npm test
```

### Development Commands

```bash
npm run build        # TypeScript compilation
npm run dev          # Watch mode for development
npm test             # Run test suite
npm run test:watch   # Watch mode for tests
npm run test:coverage # Generate coverage report
```

### Running Locally

```bash
# Run directly with tsx (no build required)
npx tsx src/main.ts

# Or run the built version
node dist/src/main.js

# With debug logging
npx tsx src/main.ts --debug
```

## Project Structure

```
src/
├── main.ts              # Entry point, CLI, TUI
├── agent.ts             # ProductionAgent core logic
├── types.ts             # Shared type definitions
├── modes.ts             # Agent modes (build, plan, review, debug)
├── providers/           # LLM provider adapters
│   └── adapters/        # Anthropic, OpenRouter, OpenAI
├── tools/               # Tool implementations
├── integrations/        # Feature modules
└── tricks/              # Context engineering techniques

tests/                   # Test files (mirror src/ structure)
docs/                    # Documentation
```

## Code Style

- TypeScript strict mode is enabled
- Use explicit types for public APIs
- Use `type` for object shapes, `interface` for contracts
- Document public functions with JSDoc comments
- Keep files focused - prefer new files over growing existing ones

### Naming Conventions

- Files: `kebab-case.ts`
- Classes: `PascalCase`
- Functions/variables: `camelCase`
- Constants: `SCREAMING_SNAKE_CASE`
- Interfaces: `PascalCase` (no `I` prefix)

## Testing

Tests live in the `tests/` directory and mirror the source structure.

```bash
# Run all tests
npm test

# Run specific test file
npx vitest run tests/providers/adapters.test.ts

# Run tests matching a pattern
npx vitest run -t "OpenAIProvider"

# Watch mode
npm run test:watch
```

### Writing Tests

Follow existing patterns in the test files. Use descriptive test names:

```typescript
describe('OpenAIProvider', () => {
  describe('chatWithTools', () => {
    it('should send tool definitions in OpenAI format', async () => {
      // ...
    });
  });
});
```

## Pull Request Process

1. **Create a branch** from `main`:
   ```bash
   git checkout -b feat/your-feature
   ```

2. **Make your changes** with clear commits

3. **Run tests** to ensure nothing is broken:
   ```bash
   npm test
   ```

4. **Run the build** to check for TypeScript errors:
   ```bash
   npm run build
   ```

5. **Create a pull request** with:
   - Clear description of changes
   - Link to any related issues
   - Screenshots if UI changes

## Adding New Features

### Adding a Provider

1. Create `src/providers/adapters/your-provider.ts`
2. Implement `LLMProvider` interface (and optionally `LLMProviderWithTools`)
3. Register with `registerProvider()` at the bottom of the file
4. Add tests in `tests/providers/adapters.test.ts`

### Adding a Tool

1. Create tool in `src/tools/your-tool.ts`
2. Implement `ToolDefinition` interface
3. Export from `src/tools/index.ts`
4. Add tests

### Adding an Integration

1. Create `src/integrations/your-integration.ts`
2. Export from `src/integrations/index.ts`
3. Add configuration types to `src/types.ts` if needed
4. Add tests

## Commit Messages

Use clear, descriptive commit messages:

```
feat: add OpenAI tool use support
fix: handle rate limit errors in resilient fetch
docs: update architecture documentation
test: add context engineering tests
refactor: consolidate TUI components
```

## Questions?

- Open an issue for bugs or feature requests
- Check existing issues before creating new ones
