/**
 * Exercise 1: Calculator Agent - REFERENCE SOLUTION
 *
 * This is the complete implementation of the calculator agent.
 * Compare your solution to understand different approaches.
 */

// =============================================================================
// TYPES
// =============================================================================

export interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface MockProvider {
  chat(messages: Message[]): Promise<{ content: string }>;
}

export interface ToolCall {
  tool: string;
  input: Record<string, unknown>;
}

export interface CalculatorResult {
  answer: number;
  iterations: number;
}

// =============================================================================
// HELPER: Parse tool call from LLM response
// =============================================================================

export function parseToolCall(response: string): ToolCall | null {
  // First, try parsing the entire response as JSON (for inline JSON)
  try {
    const parsed = JSON.parse(response.trim());
    if (parsed.tool && typeof parsed.tool === 'string') {
      return { tool: parsed.tool, input: parsed.input || {} };
    }
  } catch {
    // Not valid JSON, continue with pattern matching
  }

  // Pattern matching for code blocks
  const patterns = [
    /```json\s*([\s\S]*?)\s*```/,
    /```\s*([\s\S]*?)\s*```/,
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
        continue;
      }
    }
  }

  return null;
}

// =============================================================================
// HELPER: Calculate tool
// =============================================================================

export function calculate(expression: string): { result: number } {
  if (!/^[\d\s+\-*/().]+$/.test(expression)) {
    throw new Error(`Invalid expression: ${expression}`);
  }
  const result = computeExpression(expression);
  return { result };
}

function computeExpression(expr: string): number {
  expr = expr.replace(/\s+/g, '');
  let pos = 0;

  function parseNumber(): number {
    let numStr = '';
    while (pos < expr.length && /[\d.]/.test(expr[pos])) {
      numStr += expr[pos++];
    }
    return parseFloat(numStr);
  }

  function parseFactor(): number {
    if (expr[pos] === '(') {
      pos++;
      const result = parseAddSub();
      pos++;
      return result;
    }
    return parseNumber();
  }

  function parseMulDiv(): number {
    let result = parseFactor();
    while (pos < expr.length && (expr[pos] === '*' || expr[pos] === '/')) {
      const op = expr[pos++];
      const right = parseFactor();
      result = op === '*' ? result * right : result / right;
    }
    return result;
  }

  function parseAddSub(): number {
    let result = parseMulDiv();
    while (pos < expr.length && (expr[pos] === '+' || expr[pos] === '-')) {
      const op = expr[pos++];
      const right = parseMulDiv();
      result = op === '+' ? result + right : result - right;
    }
    return result;
  }

  return parseAddSub();
}

// =============================================================================
// SYSTEM PROMPT
// =============================================================================

const SYSTEM_PROMPT = `You are a calculator assistant. When asked to calculate something, use the calculate tool.

Available tools:
- calculate: Computes a math expression
  Input: { "expression": "math expression as string" }
  Example: { "tool": "calculate", "input": { "expression": "2 + 2" } }

When you have the final answer, respond with just the number, no tool call.`;

// =============================================================================
// SOLUTION: Calculator Agent Implementation
// =============================================================================

/**
 * Run a calculator agent that processes math questions.
 *
 * This implementation demonstrates the core agent loop pattern:
 * 1. Initialize conversation with system prompt and user task
 * 2. Loop: ask LLM -> parse response -> execute tool -> add result
 * 3. Exit when LLM provides final answer (no tool call)
 */
export async function runCalculatorAgent(
  provider: MockProvider,
  task: string
): Promise<CalculatorResult> {
  // Step 1: Initialize messages with system prompt and user task
  const messages: Message[] = [
    { role: 'system', content: SYSTEM_PROMPT },
    { role: 'user', content: task },
  ];

  // Step 2: Track iterations for the result and safety limit
  let iterations = 0;
  const maxIterations = 10;

  // Step 3: The agent loop
  while (iterations < maxIterations) {
    iterations++;

    // 3a. Get LLM response
    const response = await provider.chat(messages);

    // 3b. Add assistant's response to conversation history
    messages.push({
      role: 'assistant',
      content: response.content,
    });

    // 3c. Check if response contains a tool call
    const toolCall = parseToolCall(response.content);

    if (toolCall) {
      // 3d. Tool call found - execute it
      if (toolCall.tool === 'calculate') {
        const expression = toolCall.input.expression as string;
        const result = calculate(expression);

        // Add tool result as user message (this is how we show results to the LLM)
        messages.push({
          role: 'user',
          content: `Tool result: ${JSON.stringify(result)}`,
        });

        // Continue loop to get next LLM response
        continue;
      } else {
        throw new Error(`Unknown tool: ${toolCall.tool}`);
      }
    } else {
      // 3e. No tool call - LLM is done, extract the answer
      const numberMatch = response.content.match(/-?\d+\.?\d*/);
      if (numberMatch) {
        return {
          answer: parseFloat(numberMatch[0]),
          iterations,
        };
      }

      throw new Error(`Could not extract number from response: ${response.content}`);
    }
  }

  throw new Error(`Agent did not complete within ${maxIterations} iterations`);
}

// Export for testing
export { SYSTEM_PROMPT };
