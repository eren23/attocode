/**
 * Lesson 3: Tool Registry
 * 
 * Central registry for tool management, validation, and execution.
 */

import { z, ZodError } from 'zod';
import type { 
  ToolDefinition, 
  ToolResult, 
  ToolDescription, 
  ExecuteOptions,
  ToolEvent,
  ToolEventListener,
  PermissionChecker,
  DangerLevel
} from './types.js';
import { createPermissionChecker } from './permission.js';

// =============================================================================
// ZOD TO JSON SCHEMA CONVERTER
// =============================================================================

/**
 * Convert a Zod schema to JSON Schema for LLM tool descriptions.
 * This is a simplified converter that handles common types.
 */
function zodToJsonSchema(schema: z.ZodTypeAny): Record<string, unknown> {
  // Handle ZodObject
  if (schema instanceof z.ZodObject) {
    const shape = schema.shape;
    const properties: Record<string, unknown> = {};
    const required: string[] = [];

    for (const [key, value] of Object.entries(shape)) {
      properties[key] = zodToJsonSchema(value as z.ZodTypeAny);
      
      // Check if optional
      if (!(value instanceof z.ZodOptional)) {
        required.push(key);
      }
    }

    return {
      type: 'object',
      properties,
      ...(required.length > 0 && { required }),
    };
  }

  // Handle ZodString
  if (schema instanceof z.ZodString) {
    const result: Record<string, unknown> = { type: 'string' };
    if (schema.description) result.description = schema.description;
    return result;
  }

  // Handle ZodNumber
  if (schema instanceof z.ZodNumber) {
    const result: Record<string, unknown> = { type: 'number' };
    if (schema.description) result.description = schema.description;
    return result;
  }

  // Handle ZodBoolean
  if (schema instanceof z.ZodBoolean) {
    const result: Record<string, unknown> = { type: 'boolean' };
    if (schema.description) result.description = schema.description;
    return result;
  }

  // Handle ZodArray
  if (schema instanceof z.ZodArray) {
    return {
      type: 'array',
      items: zodToJsonSchema(schema.element),
    };
  }

  // Handle ZodEnum
  if (schema instanceof z.ZodEnum) {
    return {
      type: 'string',
      enum: schema.options,
    };
  }

  // Handle ZodOptional
  if (schema instanceof z.ZodOptional) {
    return zodToJsonSchema(schema.unwrap());
  }

  // Handle ZodDefault
  if (schema instanceof z.ZodDefault) {
    return zodToJsonSchema(schema._def.innerType);
  }

  // Fallback
  return { type: 'string' };
}

// =============================================================================
// TOOL REGISTRY
// =============================================================================

export class ToolRegistry {
  private tools: Map<string, ToolDefinition> = new Map();
  private listeners: Set<ToolEventListener> = new Set();
  private permissionChecker: PermissionChecker;

  constructor(permissionMode: ExecuteOptions['permissionMode'] = 'interactive') {
    this.permissionChecker = createPermissionChecker(permissionMode);
  }

  /**
   * Register a tool.
   */
  register<T extends z.ZodTypeAny>(tool: ToolDefinition<T>): void {
    if (this.tools.has(tool.name)) {
      throw new Error(`Tool "${tool.name}" is already registered`);
    }
    this.tools.set(tool.name, tool as ToolDefinition);
  }

  /**
   * Unregister a tool.
   */
  unregister(name: string): boolean {
    return this.tools.delete(name);
  }

  /**
   * Get a tool by name.
   */
  get(name: string): ToolDefinition | undefined {
    return this.tools.get(name);
  }

  /**
   * Check if a tool exists.
   */
  has(name: string): boolean {
    return this.tools.has(name);
  }

  /**
   * List all registered tools.
   */
  list(): string[] {
    return Array.from(this.tools.keys());
  }

  /**
   * Get tool descriptions for LLM (JSON Schema format).
   */
  getDescriptions(): ToolDescription[] {
    return Array.from(this.tools.values()).map(tool => ({
      name: tool.name,
      description: tool.description,
      input_schema: zodToJsonSchema(tool.parameters) as ToolDescription['input_schema'],
    }));
  }

  /**
   * Execute a tool by name.
   */
  async execute(
    name: string, 
    input: unknown, 
    options?: ExecuteOptions
  ): Promise<ToolResult> {
    const tool = this.tools.get(name);
    
    if (!tool) {
      return {
        success: false,
        output: `Unknown tool: "${name}". Available tools: ${this.list().join(', ')}`,
      };
    }

    this.emit({ type: 'start', tool: name, input });

    // Validate input
    let validatedInput: unknown;
    try {
      validatedInput = tool.parameters.parse(input);
    } catch (error) {
      if (error instanceof ZodError) {
        const issues = error.issues.map(i => `${i.path.join('.')}: ${i.message}`).join(', ');
        return {
          success: false,
          output: `Invalid input: ${issues}`,
        };
      }
      throw error;
    }

    // Check permissions
    const permissionRequest = {
      tool: name,
      operation: tool.description,
      target: JSON.stringify(validatedInput).slice(0, 100),
      dangerLevel: tool.dangerLevel,
    };

    this.emit({ type: 'permission_requested', request: permissionRequest });

    const permissionResponse = await this.permissionChecker.check(permissionRequest);
    
    if (!permissionResponse.granted) {
      this.emit({ 
        type: 'permission_denied', 
        request: permissionRequest, 
        reason: permissionResponse.reason ?? 'Permission denied' 
      });
      return {
        success: false,
        output: `Permission denied: ${permissionResponse.reason ?? 'Operation not allowed'}`,
      };
    }

    this.emit({ type: 'permission_granted', request: permissionRequest });
    this.emit({ type: 'executing', tool: name });

    // Execute with timeout
    try {
      const timeout = options?.timeout ?? 30000;
      const result = await Promise.race([
        tool.execute(validatedInput),
        new Promise<never>((_, reject) => 
          setTimeout(() => reject(new Error('Tool execution timed out')), timeout)
        ),
      ]);

      this.emit({ type: 'complete', tool: name, result });
      return result;
    } catch (error) {
      const err = error as Error;
      this.emit({ type: 'error', tool: name, error: err });
      return {
        success: false,
        output: `Execution error: ${err.message}`,
      };
    }
  }

  /**
   * Add an event listener.
   */
  on(listener: ToolEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Emit an event to all listeners.
   */
  private emit(event: ToolEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }

  /**
   * Update the permission checker.
   */
  setPermissionMode(mode: ExecuteOptions['permissionMode']): void {
    this.permissionChecker = createPermissionChecker(mode);
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a tool definition with type inference.
 */
export function defineTool<T extends z.ZodTypeAny>(
  name: string,
  description: string,
  parameters: T,
  execute: (input: z.infer<T>) => Promise<ToolResult>,
  dangerLevel: DangerLevel = 'safe'
): ToolDefinition<T> {
  return {
    name,
    description,
    parameters,
    dangerLevel,
    execute,
  };
}
