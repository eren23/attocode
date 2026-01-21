/**
 * Exercise 3: JSON Validator Tool - REFERENCE SOLUTION
 */

import { z } from 'zod';

// =============================================================================
// TYPES
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

export const validatorInputSchema = z.object({
  jsonData: z.string().describe('JSON string to validate'),
});

export type ValidatorInput = z.infer<typeof validatorInputSchema>;

// =============================================================================
// HELPER: Format Zod errors
// =============================================================================

export function formatZodErrors(error: z.ZodError): string {
  return error.errors
    .map(err => {
      const path = err.path.join('.');
      return path ? `${path}: ${err.message}` : err.message;
    })
    .join('; ');
}

// =============================================================================
// SOLUTION: createValidatorTool
// =============================================================================

export function createValidatorTool<T extends z.ZodTypeAny>(
  schemaName: string,
  targetSchema: T
): ToolDefinition<typeof validatorInputSchema> {
  return {
    name: `validate_${schemaName}`,
    description: `Validates JSON data against the ${schemaName} schema. Returns success if the JSON is valid, or detailed error messages if validation fails.`,
    parameters: validatorInputSchema,
    dangerLevel: 'safe',

    execute: async (input: ValidatorInput): Promise<ToolResult> => {
      // Step 1: Parse JSON string
      let parsedData: unknown;
      try {
        parsedData = JSON.parse(input.jsonData);
      } catch (parseError) {
        return {
          success: false,
          output: `Invalid JSON syntax: ${parseError instanceof Error ? parseError.message : 'Unknown error'}`,
          metadata: { stage: 'json_parse' },
        };
      }

      // Step 2: Validate against schema
      const result = targetSchema.safeParse(parsedData);

      if (result.success) {
        return {
          success: true,
          output: `Valid ${schemaName} JSON`,
          metadata: {
            validatedData: result.data,
          },
        };
      } else {
        return {
          success: false,
          output: `Validation errors for ${schemaName}: ${formatZodErrors(result.error)}`,
          metadata: {
            stage: 'schema_validation',
            errorCount: result.error.errors.length,
            errors: result.error.errors,
          },
        };
      }
    },
  };
}
