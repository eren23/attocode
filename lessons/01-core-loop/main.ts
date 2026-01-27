/**
 * Lesson 1: Main Entry Point
 * 
 * This demonstrates the agent loop with a mock LLM provider.
 * In a real scenario, you'd use an actual LLM API.
 */

import { runAgentLoop } from './loop.js';
import type { LLMProvider, Tool, ToolResult } from './types.js';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';

// =============================================================================
// MOCK LLM PROVIDER
// =============================================================================

/**
 * A mock LLM that simulates responses for testing.
 * 
 * In Lesson 2, we'll replace this with real providers.
 * For now, it demonstrates the conversation flow.
 */
class MockLLMProvider implements LLMProvider {
  private callCount = 0;

  async chat(messages: { role: string; content: string }[]): Promise<string> {
    this.callCount++;
    
    // Get the last user message
    const lastMessage = messages[messages.length - 1];
    
    // Simulate intelligent responses based on context
    if (lastMessage.content.includes('hello world') || lastMessage.content.includes('Hello World')) {
      if (this.callCount === 1) {
        // First call: create the file
        return `I'll create a hello world file for you.

\`\`\`json
{ "tool": "write_file", "input": { "path": "hello.ts", "content": "console.log('Hello, World!');" } }
\`\`\``;
      } else {
        // Second call: we're done
        return "I've created hello.ts with a simple Hello World program. You can run it with `npx tsx hello.ts`.";
      }
    }

    if (lastMessage.content.includes('list') && lastMessage.content.includes('file')) {
      if (this.callCount === 1) {
        return `I'll list the files in the current directory.

\`\`\`json
{ "tool": "list_files", "input": { "path": "." } }
\`\`\``;
      } else {
        return `Here are the files I found. The directory contains the lesson files for this course.`;
      }
    }

    // Default response for unknown tasks
    if (this.callCount === 1) {
      return `I'll help you with that task.

\`\`\`json
{ "tool": "list_files", "input": { "path": "." } }
\`\`\``;
    }
    
    return "I've examined the directory. Let me know if you need anything specific!";
  }
}

// =============================================================================
// BASIC TOOLS
// =============================================================================

/**
 * Tool to read a file.
 */
const readFileTool: Tool = {
  name: 'read_file',
  description: 'Read the contents of a file at the given path',
  
  async execute(input): Promise<ToolResult> {
    const filePath = input.path as string;
    if (!filePath) {
      return { success: false, output: 'Missing required parameter: path' };
    }
    
    try {
      const content = await fs.readFile(filePath, 'utf-8');
      return { success: true, output: content };
    } catch (error) {
      return { success: false, output: `Failed to read file: ${(error as Error).message}` };
    }
  }
};

/**
 * Tool to write a file.
 */
const writeFileTool: Tool = {
  name: 'write_file',
  description: 'Write content to a file at the given path (creates or overwrites)',
  
  async execute(input): Promise<ToolResult> {
    const filePath = input.path as string;
    const content = input.content as string;
    
    if (!filePath || content === undefined) {
      return { success: false, output: 'Missing required parameters: path and content' };
    }
    
    try {
      // Ensure directory exists
      const dir = path.dirname(filePath);
      await fs.mkdir(dir, { recursive: true });
      
      await fs.writeFile(filePath, content, 'utf-8');
      return { success: true, output: `Successfully wrote ${content.length} bytes to ${filePath}` };
    } catch (error) {
      return { success: false, output: `Failed to write file: ${(error as Error).message}` };
    }
  }
};

/**
 * Tool to list files in a directory.
 */
const listFilesTool: Tool = {
  name: 'list_files',
  description: 'List files and directories at the given path',
  
  async execute(input): Promise<ToolResult> {
    const dirPath = (input.path as string) || '.';
    
    try {
      const entries = await fs.readdir(dirPath, { withFileTypes: true });
      const formatted = entries
        .map(e => `${e.isDirectory() ? '📁' : '📄'} ${e.name}`)
        .join('\n');
      return { success: true, output: formatted || '(empty directory)' };
    } catch (error) {
      return { success: false, output: `Failed to list directory: ${(error as Error).message}` };
    }
  }
};

// =============================================================================
// MAIN
// =============================================================================

async function main() {
  // Get task from command line or use default
  const task = process.argv[2] || 'Create a hello world TypeScript file';
  
  console.log('╔════════════════════════════════════════════════════════════════╗');
  console.log('║  Lesson 1: The Core Agent Loop                                 ║');
  console.log('╚════════════════════════════════════════════════════════════════╝');
  console.log(`\nTask: ${task}\n`);

  const result = await runAgentLoop(task, {
    maxIterations: 10,
    systemPrompt: 'You are a helpful coding assistant. Complete the user\'s task using the available tools.',
    tools: [readFileTool, writeFileTool, listFilesTool],
    llm: new MockLLMProvider(),
  });

  console.log('\n════════════════════════════════════════════════════════════════');
  console.log(`Result: ${result.success ? '✅ Success' : '❌ Failed'}`);
  console.log(`Iterations: ${result.iterations}`);
  console.log(`Final message: ${result.message.slice(0, 200)}${result.message.length > 200 ? '...' : ''}`);
}

main().catch(console.error);
