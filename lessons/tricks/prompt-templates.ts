/**
 * Trick C: Prompt Templates
 *
 * Compile and render prompt templates with variable substitution.
 * Supports conditionals, loops, and escaping.
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * Compiled template function.
 */
export type CompiledTemplate = (vars: Record<string, unknown>) => string;

/**
 * Template options.
 */
export interface TemplateOptions {
  /** Delimiter for variables (default: {{ }}) */
  delimiters?: [string, string];
  /** Throw on missing variables (default: false) */
  strict?: boolean;
  /** Default value for missing variables */
  defaultValue?: string;
}

// =============================================================================
// TEMPLATE COMPILER
// =============================================================================

/**
 * Compile a template string into a function.
 *
 * Supports:
 * - {{variable}} - variable substitution
 * - {{#if condition}}...{{/if}} - conditionals
 * - {{#each items}}...{{/each}} - loops
 * - {{#trim}}...{{/trim}} - trim whitespace
 */
export function compileTemplate(
  template: string,
  options: TemplateOptions = {}
): CompiledTemplate {
  const { delimiters = ['{{', '}}'], strict = false, defaultValue = '' } = options;
  const [open, close] = delimiters;

  // Escape regex special characters
  const openEsc = escapeRegex(open);
  const closeEsc = escapeRegex(close);

  return (vars: Record<string, unknown>): string => {
    let result = template;

    // Process conditionals: {{#if condition}}...{{/if}}
    result = processConditionals(result, vars, openEsc, closeEsc);

    // Process loops: {{#each items}}...{{/each}}
    result = processLoops(result, vars, openEsc, closeEsc);

    // Process trim blocks: {{#trim}}...{{/trim}}
    result = processTrim(result, openEsc, closeEsc);

    // Process variable substitution: {{variable}}
    const varPattern = new RegExp(`${openEsc}\\s*([\\w.]+)\\s*${closeEsc}`, 'g');
    result = result.replace(varPattern, (_match, path: string) => {
      const value = getNestedValue(vars, path);
      if (value === undefined) {
        if (strict) {
          throw new Error(`Missing template variable: ${path}`);
        }
        return defaultValue;
      }
      return String(value);
    });

    return result;
  };
}

/**
 * Process conditional blocks.
 */
function processConditionals(
  template: string,
  vars: Record<string, unknown>,
  open: string,
  close: string
): string {
  const ifPattern = new RegExp(
    `${open}#if\\s+([\\w.]+)${close}([\\s\\S]*?)${open}/if${close}`,
    'g'
  );

  return template.replace(ifPattern, (_match, condition: string, content: string) => {
    const value = getNestedValue(vars, condition);
    if (isTruthy(value)) {
      // Handle else blocks
      const parts = content.split(new RegExp(`${open}else${close}`));
      return parts[0];
    } else {
      const parts = content.split(new RegExp(`${open}else${close}`));
      return parts[1] || '';
    }
  });
}

/**
 * Process loop blocks.
 */
function processLoops(
  template: string,
  vars: Record<string, unknown>,
  open: string,
  close: string
): string {
  const eachPattern = new RegExp(
    `${open}#each\\s+([\\w.]+)${close}([\\s\\S]*?)${open}/each${close}`,
    'g'
  );

  return template.replace(eachPattern, (_match, arrayPath: string, content: string) => {
    const items = getNestedValue(vars, arrayPath);
    if (!Array.isArray(items)) {
      return '';
    }

    return items
      .map((item, index) => {
        // Replace {{this}} with current item
        let itemContent = content.replace(
          new RegExp(`${open}\\s*this\\s*${close}`, 'g'),
          String(item)
        );

        // Replace {{@index}} with current index
        itemContent = itemContent.replace(
          new RegExp(`${open}\\s*@index\\s*${close}`, 'g'),
          String(index)
        );

        // If item is an object, allow {{property}} access
        if (typeof item === 'object' && item !== null) {
          const propPattern = new RegExp(`${open}\\s*([\\w]+)\\s*${close}`, 'g');
          itemContent = itemContent.replace(propPattern, (m, prop: string) => {
            if (prop === 'this' || prop.startsWith('@')) return m;
            const val = (item as Record<string, unknown>)[prop];
            return val !== undefined ? String(val) : m;
          });
        }

        return itemContent;
      })
      .join('');
  });
}

/**
 * Process trim blocks.
 */
function processTrim(template: string, open: string, close: string): string {
  const trimPattern = new RegExp(
    `${open}#trim${close}([\\s\\S]*?)${open}/trim${close}`,
    'g'
  );

  return template.replace(trimPattern, (_match, content: string) => {
    return content
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line.length > 0)
      .join('\n');
  });
}

/**
 * Get nested value from object using dot notation.
 */
function getNestedValue(obj: Record<string, unknown>, path: string): unknown {
  const parts = path.split('.');
  let current: unknown = obj;

  for (const part of parts) {
    if (current === null || current === undefined) {
      return undefined;
    }
    current = (current as Record<string, unknown>)[part];
  }

  return current;
}

/**
 * Check if value is truthy for template conditionals.
 */
function isTruthy(value: unknown): boolean {
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  return Boolean(value);
}

/**
 * Escape regex special characters.
 */
function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// =============================================================================
// PROMPT BUILDERS
// =============================================================================

/**
 * Common prompt templates.
 */
export const PROMPT_TEMPLATES = {
  /**
   * System prompt for a coding assistant.
   */
  codingAssistant: compileTemplate(`
You are an expert {{language}} developer.
{{#if context}}
Context:
{{context}}
{{/if}}

{{#if guidelines}}
Guidelines:
{{#each guidelines}}
- {{this}}
{{/each}}
{{/if}}

Help the user with their coding questions.
  `.trim()),

  /**
   * Few-shot learning prompt.
   */
  fewShot: compileTemplate(`
{{task}}

{{#if examples}}
Examples:
{{#each examples}}
Input: {{input}}
Output: {{output}}
{{/each}}
{{/if}}

Input: {{input}}
Output:
  `.trim()),

  /**
   * Chain of thought prompt.
   */
  chainOfThought: compileTemplate(`
{{task}}

Let's think step by step:
{{#each steps}}
{{@index}}. {{this}}
{{/each}}

Based on this reasoning, the answer is:
  `.trim()),

  /**
   * Summarization prompt.
   */
  summarize: compileTemplate(`
{{#trim}}
Summarize the following {{type}} in {{length}} sentences:

{{content}}

{{#if focus}}
Focus on: {{focus}}
{{/if}}
{{/trim}}
  `.trim()),
};

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Create a simple template from string.
 */
export function template(strings: TemplateStringsArray, ...keys: string[]): CompiledTemplate {
  return (vars: Record<string, unknown>) => {
    let result = strings[0];
    for (let i = 0; i < keys.length; i++) {
      result += String(vars[keys[i]] ?? '');
      result += strings[i + 1];
    }
    return result;
  };
}

/**
 * Join multiple templates.
 */
export function joinTemplates(
  templates: CompiledTemplate[],
  separator: string = '\n\n'
): CompiledTemplate {
  return (vars: Record<string, unknown>) => {
    return templates.map((t) => t(vars)).join(separator);
  };
}

// Usage:
// const greet = compileTemplate("Hello, {{name}}! You have {{count}} messages.");
// console.log(greet({ name: "Alice", count: 5 })); // "Hello, Alice! You have 5 messages."
//
// const prompt = PROMPT_TEMPLATES.fewShot({
//   task: "Translate English to French",
//   examples: [
//     { input: "Hello", output: "Bonjour" },
//     { input: "Goodbye", output: "Au revoir" },
//   ],
//   input: "Good morning",
// });
