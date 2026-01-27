# Exercise: Fixture Recorder

## Objective

Implement a fixture recorder that captures API responses for deterministic replay testing.

## Time: ~12 minutes

## Background

Testing AI agents is challenging because LLMs are non-deterministic. Fixture recording solves this by:
- Recording real API responses during development
- Replaying recorded responses during tests
- Enabling deterministic, offline testing

## Your Task

Open `exercise-1.ts` and implement the `FixtureRecorder` class.

## Requirements

1. **Record mode**: Capture requests and responses
2. **Playback mode**: Return recorded responses for matching requests
3. **Request matching**: Match by content hash
4. **Serialization**: Save/load fixtures to/from JSON

## Interface

```typescript
class FixtureRecorder {
  constructor(mode: 'record' | 'playback');

  async record(request: Request, response: Response): Promise<void>;
  async playback(request: Request): Promise<Response | null>;

  toJSON(): string;
  static fromJSON(json: string): FixtureRecorder;
}
```

## Example Usage

```typescript
// Recording
const recorder = new FixtureRecorder('record');
const response = await realApi.call(request);
await recorder.record(request, response);
fs.writeFileSync('fixtures.json', recorder.toJSON());

// Playback
const fixtures = FixtureRecorder.fromJSON(fs.readFileSync('fixtures.json'));
const response = await fixtures.playback(request);
```

## Testing Your Solution

```bash
npm run test:lesson:6:exercise
```

## Hints

1. Use JSON.stringify for creating request hashes
2. Store fixtures in a Map keyed by request hash
3. Consider ordering: recorded fixtures should replay in sequence
4. Handle missing fixtures gracefully in playback mode

## Files

- `exercise-1.ts` - Your implementation (has TODOs)
- `answers/exercise-1.ts` - Reference solution
