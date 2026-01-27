/**
 * Exercise 1: Calculator Agent
 *
 * Implement a simple calculator agent that demonstrates the core agent loop.
 *
 * The agent should:
 * 1. Send the user's task to the LLM
 * 2. Parse any tool calls from the response
 * 3. Execute the calculate tool when requested
 * 4. Continue until the LLM provides a final answer
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

/**
 * Extract a tool call from the LLM's response.
 * Looks for JSON in the format: { "tool": "name", "input": { ... } }
 */
export function parseToolCall(response: string): ToolCall | null {
  const patterns = [
    /```json\s*(\{[\s\S]*?\})\s*```/,
    /```\s*(\{[\s\S]*?\})\s*```/,
    /(\{\s*"tool"\s*:[\s\S]*?\})/,
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

/**
 * Simple calculator that computes math expressions.
 * Uses a safe recursive descent parser (no code execution).
 *
 * NOTE: This is a simplified implementation for learning purposes.
 * In production, use a proper math parser library like mathjs.
 */
export function calculate(expression: string): { result: number } {
  // Safety: Only allow numbers and basic operators
  if (!/^[\d\s+\-*/().]+$/.test(expression)) {
    throw new Error(`Invalid expression: ${expression}`);
  }

  // Use safe recursive descent parser
  const result = computeExpression(expression);
  return { result };
}

// Safe expression parser using recursive descent (no dynamic code)
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
      pos++; // skip ')'
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
// TODO: Implement the calculator agent
// =============================================================================

/**
 * Run a calculator agent that processes math questions.
 *
 * @param provider - Mock LLM provider
 * @param task - User's math question (e.g., "What is 25 * 4?")
 * @returns The final answer and number of iterations
 *
 * TODO: Implement this function following these steps:
 *
 * 1. Initialize the messages array with:
 *    - A system message with SYSTEM_PROMPT
 *    - A user message with the task
 *
 * 2. Create an agent loop that:
 *    a. Calls provider.chat(messages) to get the LLM response
 *    b. Adds the assistant's response to messages
 *    c. Parses the response for a tool call using parseToolCall()
 *    d. If there's a tool call:
 *       - Execute the calculate tool
 *       - Add the result as a user message
 *       - Continue the loop
 *    e. If there's no tool call:
 *       - Extract the number from the response
 *       - Return the result
 *
 * 3. Include a maximum iteration limit (e.g., 10) to prevent infinite loops
 */
export async function runCalculatorAgent(
  provider: MockProvider,
  task: string
): Promise<CalculatorResult> {
  // TODO: Initialize messages array
  // const messages: Message[] = [
  //   { role: 'system', content: SYSTEM_PROMPT },
  //   { role: 'user', content: task },
  // ];

  // TODO: Track iterations
  // let iterations = 0;
  // const maxIterations = 10;

  // TODO: Implement the agent loop
  // while (iterations < maxIterations) {
  //   iterations++;
  //
  //   // 1. Get LLM response
  //
  //   // 2. Add response to messages
  //
  //   // 3. Check for tool call
  //
  //   // 4. If tool call, execute and continue
  //
  //   // 5. If no tool call, extract answer and return
  // }

  // TODO: Remove this placeholder and implement the real logic
  throw new Error('TODO: Implement runCalculatorAgent');
}

// Export for testing
export { SYSTEM_PROMPT };
