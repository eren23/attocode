/**
 * Lesson 1: The Agent Loop
 * 
 * This is the heart of any AI agent - a loop that:
 * 1. Asks the LLM what to do
 * 2. Executes the requested action
 * 3. Shows the result to the LLM
 * 4. Repeats until done
 */

import type { 
  AgentConfig, 
  AgentResult, 
  Message, 
  Tool, 
  ToolCall 
} from './types.js';

// =============================================================================
// TOOL CALL PARSING
// =============================================================================

/**
 * Parse a tool call from the LLM's response.
 * 
 * The LLM outputs JSON in this format:
 * ```json
 * { "tool": "read_file", "input": { "path": "hello.txt" } }
 * ```
 * 
 * We look for this JSON in the response and extract it.
 */
export function parseToolCall(response: string): ToolCall | null {
  // Try to find JSON in the response
  // We support both ```json blocks and raw JSON
  const patterns = [
    /```json\s*(\{[\s\S]*?\})\s*```/,  // ```json { ... } ```
    /```\s*(\{[\s\S]*?\})\s*```/,       // ``` { ... } ```
    /(\{\s*"tool"\s*:[\s\S]*?\})/,      // Raw JSON with "tool" key
  ];

  for (const pattern of patterns) {
    const match = response.match(pattern);
    if (match) {
      try {
        const parsed = JSON.parse(match[1]);
        if (parsed.tool && typeof parsed.tool === 'string') {
          return {
            tool: parsed.tool,
            input: parsed.input || {},
          };
        }
      } catch {
        // JSON parse failed, try next pattern
        continue;
      }
    }
  }

  return null;
}

/**
 * Build the system prompt that tells the LLM how to use tools.
 */
function buildSystemPrompt(config: AgentConfig): string {
  const toolDescriptions = config.tools
    .map(t => `- ${t.name}: ${t.description}`)
    .join('\n');

  return `${config.systemPrompt}

You have access to these tools:
${toolDescriptions}

To use a tool, respond with JSON in this exact format:
\`\`\`json
{ "tool": "tool_name", "input": { "param": "value" } }
\`\`\`

When the task is complete, respond normally without a tool call.
Be concise and focused on completing the task.`;
}

/**
 * Find a tool by name.
 */
function findTool(tools: Tool[], name: string): Tool | undefined {
  return tools.find(t => t.name === name);
}

// =============================================================================
// THE AGENT LOOP
// =============================================================================

/**
 * Run the agent loop.
 * 
 * This is the core of our agent. It:
 * 1. Sends the task to the LLM
 * 2. Parses any tool calls from the response
 * 3. Executes tools and feeds results back
 * 4. Repeats until done or max iterations reached
 * 
 * @param task - The task for the agent to complete
 * @param config - Agent configuration
 * @returns Result of the agent run
 */
export async function runAgentLoop(
  task: string, 
  config: AgentConfig
): Promise<AgentResult> {
  // Initialize conversation with system prompt and user task
  const messages: Message[] = [
    { role: 'system', content: buildSystemPrompt(config) },
    { role: 'user', content: task },
  ];

  let iterations = 0;

  // The main loop
  while (iterations < config.maxIterations) {
    iterations++;
    console.log(`\n--- Iteration ${iterations}/${config.maxIterations} ---`);

    // Step 1: Ask the LLM what to do
    let response: string;
    try {
      response = await config.llm.chat(messages);
    } catch (error) {
      return {
        success: false,
        message: `LLM error: ${(error as Error).message}`,
        iterations,
        history: messages,
      };
    }

    // Add assistant response to history
    messages.push({ role: 'assistant', content: response });

    // Step 2: Check if it wants to use a tool
    const toolCall = parseToolCall(response);

    if (!toolCall) {
      // No tool call means the agent thinks it's done
      console.log('✅ Task completed');
      return {
        success: true,
        message: response,
        iterations,
        history: messages,
      };
    }

    // Step 3: Find and execute the tool
    console.log(`🔧 Tool: ${toolCall.tool}`);
    console.log(`   Input: ${JSON.stringify(toolCall.input)}`);

    const tool = findTool(config.tools, toolCall.tool);
    
    if (!tool) {
      // Unknown tool - tell the LLM
      const errorMsg = `Error: Unknown tool "${toolCall.tool}". Available tools: ${config.tools.map(t => t.name).join(', ')}`;
      console.log(`   ❌ ${errorMsg}`);
      messages.push({ role: 'user', content: errorMsg });
      continue;
    }

    // Execute the tool
    let result;
    try {
      result = await tool.execute(toolCall.input);
    } catch (error) {
      result = {
        success: false,
        output: `Tool execution error: ${(error as Error).message}`,
      };
    }

    // Step 4: Feed result back to the LLM
    const resultMessage = result.success 
      ? `Tool result:\n${result.output}`
      : `Tool error:\n${result.output}`;
    
    console.log(`   → ${result.output.slice(0, 100)}${result.output.length > 100 ? '...' : ''}`);
    messages.push({ role: 'user', content: resultMessage });
  }

  // Hit max iterations
  return {
    success: false,
    message: `Max iterations (${config.maxIterations}) reached without completing task`,
    iterations,
    history: messages,
  };
}
