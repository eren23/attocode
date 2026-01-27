/**
 * Exercise 3: JSON Validator Tool
 *
 * Create a tool that validates JSON against a Zod schema.
 * This demonstrates the tool definition pattern with validation.
 */

import { z } from 'zod';

// =============================================================================
// TYPES (from lesson 3)
// =============================================================================

export type DangerLevel = 'safe' | 'moderate' | 'dangerous' | 'critical';

export interface ToolResult {
  success: boolean;
  output: string;
  metadata?: Record<string, unknown>;
}

export interface ToolDefinition<TInput extends z.ZodTypeAny = z.ZodTypeAny> {
  name: string;
  description: string;
  parameters: TInput;
  dangerLevel: DangerLevel;
  execute: (input: z.infer<TInput>) => Promise<ToolResult>;
}

// =============================================================================
// TOOL INPUT SCHEMA
// =============================================================================

/**
 * Schema for the validator tool's input.
 * The tool receives JSON as a string to validate.
 */
export const validatorInputSchema = z.object({
  jsonData: z.string().describe('JSON string to validate'),
});

export type ValidatorInput = z.infer<typeof validatorInputSchema>;

// =============================================================================
// TODO: Implement createValidatorTool
// =============================================================================

/**
 * Creates a JSON validator tool for a specific schema.
 *
 * @param schemaName - Name identifying what this validator checks (e.g., "user", "config")
 * @param targetSchema - Zod schema to validate against
 * @returns A ToolDefinition that validates JSON data
 *
 * TODO: Implement this function following these requirements:
 *
 * 1. Return a ToolDefinition object with:
 *    - name: `validate_${schemaName}` (e.g., "validate_user")
 *    - description: Explains what the tool validates
 *    - parameters: validatorInputSchema
 *    - dangerLevel: 'safe'
 *    - execute: async function that validates input
 *
 * 2. The execute function should:
 *    a. Parse the jsonData string using JSON.parse()
 *    b. Validate the parsed object against targetSchema
 *    c. Return success: true if valid
 *    d. Return success: false with error details if invalid
 *
 * 3. Handle errors:
 *    - Invalid JSON syntax: return clear error message
 *    - Validation failure: return formatted Zod errors
 */
export function createValidatorTool<T extends z.ZodTypeAny>(
  schemaName: string,
  targetSchema: T
): ToolDefinition<typeof validatorInputSchema> {
  // TODO: Return a ToolDefinition object
  //
  // return {
  //   name: `validate_${schemaName}`,
  //   description: `Validates JSON data against the ${schemaName} schema`,
  //   parameters: validatorInputSchema,
  //   dangerLevel: 'safe',
  //   execute: async (input: ValidatorInput): Promise<ToolResult> => {
  //     // TODO: Implement validation logic
  //   },
  // };

  throw new Error('TODO: Implement createValidatorTool');
}

// =============================================================================
// HELPER: Format Zod errors
// =============================================================================

/**
 * Format Zod validation errors into a readable string.
 * You can use this in your execute function.
 */
export function formatZodErrors(error: z.ZodError): string {
  return error.errors
    .map(err => {
      const path = err.path.join('.');
      return path ? `${path}: ${err.message}` : err.message;
    })
    .join('; ');
}
