/**
 * Lesson 4: Streaming Demo
 * 
 * Demonstrates streaming responses with real-time terminal output.
 */

import { 
  MockStreamingProvider, 
  AnthropicStreamingProvider, 
  consumeStream,
  text,
  done
} from './stream.js';
import { createStreamRenderer, createSpinner } from './ui.js';
import { tryParseToolCall } from './parser.js';
import type { StreamEvent, StreamMessage } from './types.js';

// =============================================================================
// STREAMING AGENT
// =============================================================================

/**
 * A simple streaming agent that demonstrates the concepts.
 */
async function runStreamingAgent(task: string, useMock = true) {
  // Create provider
  const provider = useMock 
    ? new MockStreamingProvider()
    : new AnthropicStreamingProvider();

  console.log(`🔌 Using provider: ${provider.name}`);

  // Build messages
  const messages: StreamMessage[] = [
    { 
      role: 'system', 
      content: `You are a helpful coding assistant. Complete the user's task using tools.

To use a tool, output JSON in a code block:
\`\`\`json
{ "tool": "tool_name", "input": { "param": "value" } }
\`\`\`

Available tools: list_files, read_file, write_file` 
    },
    { role: 'user', content: task },
  ];

  // Create renderer
  const renderer = createStreamRenderer({
    showTools: true,
    showThinking: true,
    theme: 'default',
  });

  // Start streaming
  console.log('\n--- Streaming Response ---\n');

  const stream = provider.streamChat(messages, {
    maxTokens: 2048,
    temperature: 0.7,
  });

  // Process stream with tool detection
  let textBuffer = '';
  
  for await (const event of stream) {
    // Render the event
    renderer(event);

    // Accumulate text to detect tool calls
    if (event.type === 'text') {
      textBuffer += event.text;

      // Check for complete tool calls
      const toolCall = tryParseToolCall(textBuffer);
      if (toolCall) {
        // Simulate tool execution
        await simulateToolExecution(toolCall.tool, toolCall.input, renderer);
        
        // Clear buffer after tool call
        textBuffer = textBuffer.slice(toolCall.endIndex);
      }
    }
  }
}

/**
 * Simulate tool execution with streaming feedback.
 */
async function simulateToolExecution(
  tool: string,
  input: Record<string, unknown>,
  renderer: (event: StreamEvent) => void
) {
  const id = Math.random().toString(36).slice(2, 8);

  // Emit tool start
  renderer({ type: 'tool_start', id, tool });
  renderer({ type: 'tool_input', id, input });

  // Simulate execution time
  const spinner = createSpinner('Executing...');
  await new Promise(resolve => setTimeout(resolve, 500));
  spinner.stop();

  // Emit result
  const result = simulateToolResult(tool, input);
  renderer({ type: 'tool_end', id, ...result });
}

function simulateToolResult(
  tool: string, 
  input: Record<string, unknown>
): { success: boolean; output: string } {
  switch (tool) {
    case 'list_files':
      return {
        success: true,
        output: '📁 src/\n📁 tests/\n📄 package.json\n📄 tsconfig.json\n📄 README.md',
      };
    case 'read_file':
      return {
        success: true,
        output: `Contents of ${input.path}:\n\nexport function main() {\n  console.log('Hello, World!');\n}`,
      };
    case 'write_file':
      return {
        success: true,
        output: `Successfully wrote ${(input.content as string)?.length ?? 0} bytes to ${input.path}`,
      };
    default:
      return {
        success: false,
        output: `Unknown tool: ${tool}`,
      };
  }
}

// =============================================================================
// DEMO: CUSTOM STREAM
// =============================================================================

/**
 * Demonstrate creating a custom stream.
 */
async function* customStream(): AsyncGenerator<StreamEvent> {
  yield text('Starting analysis...\n\n');
  await sleep(100);

  yield { type: 'thinking', text: 'Considering the best approach...' };
  await sleep(200);

  yield text('I\'ll break this down into steps:\n');
  yield text('1. Read the file\n');
  await sleep(50);
  yield text('2. Analyze the code\n');
  await sleep(50);
  yield text('3. Make improvements\n\n');
  await sleep(100);

  yield { type: 'tool_start', id: 'tool1', tool: 'read_file' };
  yield { type: 'tool_input', id: 'tool1', input: { path: 'main.ts' } };
  await sleep(300);
  yield { type: 'tool_end', id: 'tool1', success: true, output: 'export function main() { ... }' };

  yield text('\nAnalysis complete. ');
  yield text('The code looks good!\n');

  yield done();
}

// =============================================================================
// MAIN
// =============================================================================

async function main() {
  console.log('╔════════════════════════════════════════════════════════════════╗');
  console.log('║  Lesson 4: Streaming Responses                                 ║');
  console.log('╚════════════════════════════════════════════════════════════════╝');

  const demo = process.argv[2] || 'mock';

  switch (demo) {
    case 'mock':
      console.log('\n📺 Demo: Mock streaming provider\n');
      await runStreamingAgent('List the files in the current directory', true);
      break;

    case 'anthropic':
      console.log('\n📺 Demo: Anthropic streaming provider\n');
      if (!process.env.ANTHROPIC_API_KEY) {
        console.log('❌ ANTHROPIC_API_KEY not set. Using mock instead.');
        await runStreamingAgent('List the files in the current directory', true);
      } else {
        await runStreamingAgent('What is 2 + 2?', false);
      }
      break;

    case 'custom':
      console.log('\n📺 Demo: Custom stream\n');
      const renderer = createStreamRenderer({ showTools: true, theme: 'colorful' });
      await consumeStream(customStream(), { onEvent: renderer });
      break;

    default:
      console.log('\nUsage: npx tsx 04-streaming/main.ts [mock|anthropic|custom]');
  }

  console.log('\n════════════════════════════════════════════════════════════════');
  console.log('\n📝 Key Concepts Demonstrated:');
  console.log('   1. Async generators for streaming');
  console.log('   2. SSE parsing for LLM APIs');
  console.log('   3. Real-time terminal rendering');
  console.log('   4. Tool call detection in streams');
  console.log('\nTry different demos:');
  console.log('   npx tsx 04-streaming/main.ts mock');
  console.log('   npx tsx 04-streaming/main.ts custom');
  console.log('   ANTHROPIC_API_KEY=xxx npx tsx 04-streaming/main.ts anthropic');
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

main().catch(console.error);
