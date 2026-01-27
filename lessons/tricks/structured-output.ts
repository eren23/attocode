/**
 * Trick A: Structured Output Parsing
 *
 * Parse LLM outputs into strongly-typed structures with retry logic.
 * Uses schema validation to ensure output matches expected format.
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * Simple schema type for validation.
 * In production, use Zod or similar library.
 */
export interface Schema<T> {
  parse(value: unknown): T;
  safeParse(value: unknown): { success: true; data: T } | { success: false; error: Error };
}

/**
 * LLM provider interface (minimal).
 */
export interface LLMProvider {
  generate(prompt: string): Promise<string>;
}

/**
 * Parse options.
 */
export interface ParseOptions {
  maxRetries?: number;
  includeSchema?: boolean;
  temperature?: number;
}

// =============================================================================
// STRUCTURED OUTPUT PARSER
// =============================================================================

/**
 * Parse LLM output into structured format with retries.
 */
export async function parseStructured<T>(
  provider: LLMProvider,
  prompt: string,
  schema: Schema<T>,
  options: ParseOptions = {}
): Promise<T> {
  const { maxRetries = 3, includeSchema = true } = options;

  let lastError: Error | null = null;
  let lastOutput: string = '';

  for (let attempt = 0; attempt < maxRetries; attempt++) {
    // Build prompt with schema hint
    const fullPrompt = includeSchema
      ? `${prompt}\n\nRespond with valid JSON only. No explanation or markdown.`
      : prompt;

    // Add retry context if needed
    const retryPrompt =
      attempt > 0
        ? `${fullPrompt}\n\nPrevious attempt failed with error: ${lastError?.message}\nPrevious output: ${lastOutput}\n\nPlease fix the JSON format.`
        : fullPrompt;

    try {
      const output = await provider.generate(retryPrompt);
      lastOutput = output;

      // Extract JSON from response (handle markdown code blocks)
      const jsonStr = extractJson(output);

      // Parse JSON
      const parsed = JSON.parse(jsonStr);

      // Validate against schema
      const result = schema.safeParse(parsed);

      if (result.success) {
        return result.data;
      }

      lastError = result.error;
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));
    }
  }

  throw new Error(
    `Failed to parse structured output after ${maxRetries} attempts: ${lastError?.message}`
  );
}

/**
 * Extract JSON from LLM output (handles markdown code blocks).
 */
export function extractJson(text: string): string {
  // Try to extract from code block first
  const codeBlockMatch = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (codeBlockMatch) {
    return codeBlockMatch[1].trim();
  }

  // Try to find JSON object or array
  const jsonMatch = text.match(/(\{[\s\S]*\}|\[[\s\S]*\])/);
  if (jsonMatch) {
    return jsonMatch[1];
  }

  // Return as-is
  return text.trim();
}

// =============================================================================
// SIMPLE SCHEMA BUILDERS
// =============================================================================

/**
 * Create a schema for an object with required fields.
 */
export function objectSchema<T extends Record<string, unknown>>(
  validator: (value: unknown) => value is T
): Schema<T> {
  return {
    parse(value: unknown): T {
      if (validator(value)) {
        return value;
      }
      throw new Error('Object validation failed');
    },
    safeParse(value: unknown) {
      try {
        return { success: true, data: this.parse(value) };
      } catch (err) {
        return { success: false, error: err instanceof Error ? err : new Error(String(err)) };
      }
    },
  };
}

/**
 * Create a schema for an array of items.
 */
export function arraySchema<T>(itemSchema: Schema<T>): Schema<T[]> {
  return {
    parse(value: unknown): T[] {
      if (!Array.isArray(value)) {
        throw new Error('Expected array');
      }
      return value.map((item) => itemSchema.parse(item));
    },
    safeParse(value: unknown) {
      try {
        return { success: true, data: this.parse(value) };
      } catch (err) {
        return { success: false, error: err instanceof Error ? err : new Error(String(err)) };
      }
    },
  };
}

// =============================================================================
// EXAMPLE USAGE
// =============================================================================

// Example schema for a task extraction
interface ExtractedTask {
  title: string;
  priority: 'low' | 'medium' | 'high';
  dueDate?: string;
}

function isExtractedTask(value: unknown): value is ExtractedTask {
  if (typeof value !== 'object' || value === null) return false;
  const obj = value as Record<string, unknown>;
  return (
    typeof obj.title === 'string' &&
    ['low', 'medium', 'high'].includes(obj.priority as string)
  );
}

export const taskSchema = objectSchema(isExtractedTask);

// Usage:
// const task = await parseStructured(llm, "Extract the task from: 'Submit report by Friday'", taskSchema);
// console.log(task); // { title: "Submit report", priority: "high", dueDate: "Friday" }
