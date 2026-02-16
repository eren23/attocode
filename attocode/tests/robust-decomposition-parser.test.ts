/**
 * Tests for robust decomposition parser.
 *
 * Validates that parseDecompositionResponse handles messy LLM output:
 * - Lenient JSON repair (trailing commas, comments, single quotes, unquoted keys)
 * - Natural language extraction (numbered lists, bulleted lists, markdown task lists)
 * - Single mega-task fallback
 */
import { describe, it, expect } from 'vitest';
import {
  parseDecompositionResponse,
  repairJSON,
  extractSubtasksFromNaturalLanguage,
} from '../src/integrations/smart-decomposer.js';

// =============================================================================
// Layer 0: Standard JSON (existing behavior preserved)
// =============================================================================

describe('parseDecompositionResponse — standard JSON', () => {
  it('should parse well-formed JSON in code block', () => {
    const response = '```json\n{"subtasks":[{"description":"Task A","type":"implement","complexity":3,"dependencies":[],"parallelizable":true}],"strategy":"adaptive","reasoning":"test"}\n```';
    const result = parseDecompositionResponse(response);
    expect(result.subtasks).toHaveLength(1);
    expect(result.subtasks[0].description).toBe('Task A');
    expect(result.parseError).toBeUndefined();
  });

  it('should parse raw JSON without code block', () => {
    const response = '{"subtasks":[{"description":"Task A","type":"implement","complexity":3,"dependencies":[],"parallelizable":true}],"strategy":"sequential","reasoning":"test"}';
    const result = parseDecompositionResponse(response);
    expect(result.subtasks).toHaveLength(1);
    expect(result.strategy).toBe('sequential');
  });

  it('should handle array-at-root', () => {
    const response = '[{"description":"Task A","type":"implement","complexity":3,"dependencies":[],"parallelizable":true},{"description":"Task B","type":"test","complexity":2,"dependencies":["0"],"parallelizable":false}]';
    const result = parseDecompositionResponse(response);
    expect(result.subtasks).toHaveLength(2);
    expect(result.subtasks[1].type).toBe('test');
  });

  it('should normalize alternative key names: tasks, steps, task_list', () => {
    const response = '{"tasks":[{"description":"One","type":"implement","complexity":3,"dependencies":[],"parallelizable":true}],"strategy":"parallel"}';
    const result = parseDecompositionResponse(response);
    expect(result.subtasks).toHaveLength(1);

    const response2 = '{"steps":[{"desc":"Two","type":"design","complexity":4,"deps":[],"parallel":true}]}';
    const result2 = parseDecompositionResponse(response2);
    expect(result2.subtasks).toHaveLength(1);
    expect(result2.subtasks[0].description).toBe('Two');
  });

  it('should return empty for empty response', () => {
    const result = parseDecompositionResponse('');
    expect(result.subtasks).toHaveLength(0);
    expect(result.parseError).toBe('Empty response from LLM');
  });
});

// =============================================================================
// Layer 1: Lenient JSON repair
// =============================================================================

describe('repairJSON', () => {
  it('should strip trailing commas', () => {
    const input = '{"subtasks": [{"description": "A",}, {"description": "B",},]}';
    const repaired = repairJSON(input);
    expect(() => JSON.parse(repaired)).not.toThrow();
    const parsed = JSON.parse(repaired);
    expect(parsed.subtasks).toHaveLength(2);
  });

  it('should strip JS line comments', () => {
    const input = `{
      // This is a comment
      "subtasks": [
        {"description": "Task A", "type": "implement"} // inline comment
      ]
    }`;
    const repaired = repairJSON(input);
    expect(() => JSON.parse(repaired)).not.toThrow();
  });

  it('should strip JS block comments', () => {
    const input = `{
      /* This is a block comment */
      "subtasks": [
        {"description": "Task A" /* another comment */, "type": "implement"}
      ]
    }`;
    const repaired = repairJSON(input);
    expect(() => JSON.parse(repaired)).not.toThrow();
  });

  it('should replace single quotes with double quotes', () => {
    const input = "{'subtasks': [{'description': 'Task A', 'type': 'implement'}]}";
    const repaired = repairJSON(input);
    expect(() => JSON.parse(repaired)).not.toThrow();
    const parsed = JSON.parse(repaired);
    expect(parsed.subtasks[0].description).toBe('Task A');
  });

  it('should fix unquoted object keys', () => {
    const input = '{subtasks: [{description: "Task A", type: "implement", complexity: 3}]}';
    const repaired = repairJSON(input);
    expect(() => JSON.parse(repaired)).not.toThrow();
    const parsed = JSON.parse(repaired);
    expect(parsed.subtasks[0].description).toBe('Task A');
  });

  it('should not mangle strings containing colons', () => {
    const input = '{"description": "Step 1: Do something", "type": "implement"}';
    const repaired = repairJSON(input);
    const parsed = JSON.parse(repaired);
    expect(parsed.description).toBe('Step 1: Do something');
  });

  it('should handle combined issues', () => {
    const input = `{
      // Decomposition result
      subtasks: [
        {'description': 'Research the codebase', 'type': 'research', complexity: 3, dependencies: [], parallelizable: true,},
        {'description': 'Implement the feature', 'type': 'implement', complexity: 6, dependencies: ['0'], parallelizable: false,},
      ],
      strategy: 'sequential',
    }`;
    const repaired = repairJSON(input);
    expect(() => JSON.parse(repaired)).not.toThrow();
    const parsed = JSON.parse(repaired);
    expect(parsed.subtasks).toHaveLength(2);
  });
});

describe('parseDecompositionResponse — lenient JSON repair', () => {
  it('should parse JSON with trailing commas', () => {
    const response = '{"subtasks": [{"description": "Task A", "type": "implement", "complexity": 3, "dependencies": [], "parallelizable": true,},], "strategy": "adaptive",}';
    const result = parseDecompositionResponse(response);
    expect(result.subtasks).toHaveLength(1);
    expect(result.subtasks[0].description).toBe('Task A');
  });

  it('should parse JSON with single quotes (common from weaker models)', () => {
    const response = "{'subtasks': [{'description': 'Create user model', 'type': 'implement', 'complexity': 4, 'dependencies': [], 'parallelizable': false}, {'description': 'Add API endpoints', 'type': 'implement', 'complexity': 5, 'dependencies': ['0'], 'parallelizable': false}], 'strategy': 'sequential'}";
    const result = parseDecompositionResponse(response);
    expect(result.subtasks).toHaveLength(2);
    expect(result.subtasks[0].description).toBe('Create user model');
  });

  it('should parse JSON with JS comments', () => {
    const response = `\`\`\`json
{
  // Here are the subtasks
  "subtasks": [
    {"description": "Analyze requirements", "type": "research", "complexity": 2, "dependencies": [], "parallelizable": true},
    {"description": "Implement solution", "type": "implement", "complexity": 5, "dependencies": [0], "parallelizable": false}
  ],
  "strategy": "sequential" /* always sequential for this */
}
\`\`\``;
    const result = parseDecompositionResponse(response);
    expect(result.subtasks).toHaveLength(2);
  });

  it('should parse JSON with unquoted keys', () => {
    const response = '{subtasks: [{ description: "Design schema", type: "design", complexity: 4, dependencies: [], parallelizable: false }], strategy: "adaptive"}';
    const result = parseDecompositionResponse(response);
    expect(result.subtasks).toHaveLength(1);
    expect(result.subtasks[0].description).toBe('Design schema');
  });

  it('should annotate reasoning with (repaired JSON)', () => {
    const response = "{'subtasks': [{'description': 'Task X', 'type': 'implement', 'complexity': 3, 'dependencies': [], 'parallelizable': true}], 'strategy': 'adaptive', 'reasoning': 'original'}";
    const result = parseDecompositionResponse(response);
    expect(result.reasoning).toContain('repaired JSON');
  });
});

// =============================================================================
// Layer 2: Natural language extraction
// =============================================================================

describe('extractSubtasksFromNaturalLanguage', () => {
  it('should extract from numbered list (period separator)', () => {
    const response = `Here's my decomposition:

1. Research the existing authentication system
2. Design the new OAuth integration
3. Implement OAuth provider adapter
4. Write integration tests for the auth flow
5. Deploy the changes to staging`;

    const result = extractSubtasksFromNaturalLanguage(response);
    expect(result).not.toBeNull();
    expect(result!.subtasks).toHaveLength(5);
    expect(result!.subtasks[0].description).toBe('Research the existing authentication system');
    expect(result!.subtasks[0].type).toBe('research');
    expect(result!.subtasks[2].type).toBe('implement');
    expect(result!.subtasks[3].type).toBe('test');
    expect(result!.subtasks[4].type).toBe('deploy');
  });

  it('should extract from numbered list (parenthesis separator)', () => {
    const response = `1) Analyze the current codebase structure
2) Design the refactoring approach
3) Implement the new module system
4) Verify all tests still pass`;

    const result = extractSubtasksFromNaturalLanguage(response);
    expect(result).not.toBeNull();
    expect(result!.subtasks).toHaveLength(4);
    expect(result!.subtasks[0].description).toBe('Analyze the current codebase structure');
  });

  it('should extract from bulleted list', () => {
    const response = `The task can be broken down as follows:

- Research existing similar implementations in the codebase
- Design the component interface and props
- Implement the core component logic
- Write unit tests for edge cases`;

    const result = extractSubtasksFromNaturalLanguage(response);
    expect(result).not.toBeNull();
    expect(result!.subtasks).toHaveLength(4);
    expect(result!.subtasks[0].type).toBe('research');
    expect(result!.subtasks[1].type).toBe('design');
  });

  it('should extract from markdown task lists', () => {
    const response = `## Decomposition

- [ ] Investigate the bug in the login flow
- [ ] Design a fix for the token refresh
- [x] Implement the session expiry handler
- [ ] Verify the fix works end-to-end`;

    const result = extractSubtasksFromNaturalLanguage(response);
    expect(result).not.toBeNull();
    expect(result!.subtasks).toHaveLength(4);
    expect(result!.subtasks[0].description).toBe('Investigate the bug in the login flow');
  });

  it('should extract from "Task N:" style headers', () => {
    const response = `Task 1: Research the existing API structure and identify patterns
Task 2: Design the new endpoint schema
Task 3: Implement CRUD operations for users
Task 4: Write comprehensive test coverage`;

    const result = extractSubtasksFromNaturalLanguage(response);
    expect(result).not.toBeNull();
    expect(result!.subtasks).toHaveLength(4);
  });

  it('should extract from "Step N:" style headers', () => {
    const response = `Step 1: Understand the current database schema
Step 2: Plan the migration strategy
Step 3: Implement the migration scripts`;

    const result = extractSubtasksFromNaturalLanguage(response);
    expect(result).not.toBeNull();
    expect(result!.subtasks).toHaveLength(3);
  });

  it('should assign sequential dependencies', () => {
    const response = `1. Research the problem space thoroughly
2. Design the solution architecture
3. Implement the core features`;

    const result = extractSubtasksFromNaturalLanguage(response);
    expect(result).not.toBeNull();
    expect(result!.subtasks[0].dependencies).toEqual([]);
    expect(result!.subtasks[1].dependencies).toEqual(['0']);
    expect(result!.subtasks[2].dependencies).toEqual(['1']);
  });

  it('should infer task types from keywords', () => {
    const response = `1. Investigate the error logs and understand root cause
2. Design a robust error handling strategy
3. Refactor the existing error handlers
4. Write tests to verify the new behavior
5. Document the changes in the README`;

    const result = extractSubtasksFromNaturalLanguage(response);
    expect(result).not.toBeNull();
    expect(result!.subtasks[0].type).toBe('research');
    expect(result!.subtasks[1].type).toBe('design');
    expect(result!.subtasks[2].type).toBe('refactor');
    expect(result!.subtasks[3].type).toBe('test');
    expect(result!.subtasks[4].type).toBe('document');
  });

  it('should return null when fewer than 2 items found', () => {
    const response = 'Just implement the whole thing in one go.';
    const result = extractSubtasksFromNaturalLanguage(response);
    expect(result).toBeNull();
  });

  it('should skip items shorter than 6 chars', () => {
    const response = `1. Hi
2. Also short text that's actually fine
3. Do it`;
    const result = extractSubtasksFromNaturalLanguage(response);
    // "Hi" and "Do it" are <= 5 chars, only "Also short text..." qualifies
    expect(result).toBeNull();
  });
});

describe('parseDecompositionResponse — natural language fallback', () => {
  it('should fall back to numbered list when response has no JSON at all', () => {
    const response = `I'll break this down into the following tasks:

1. Set up the project structure and dependencies
2. Implement the database schema and migrations
3. Build the REST API endpoints
4. Add authentication middleware
5. Write integration tests`;

    const result = parseDecompositionResponse(response);
    expect(result.subtasks).toHaveLength(5);
    expect(result.subtasks[0].description).toBe('Set up the project structure and dependencies');
    expect(result.reasoning).toBe('(extracted from natural language list)');
    expect(result.parseError).toBeUndefined();
  });

  it('should fall back to bullet list after invalid JSON', () => {
    const response = `Here is the decomposition: {invalid json that won't parse properly

- Research the authentication patterns used in similar projects
- Design the token refresh mechanism
- Implement the OAuth2 flow with PKCE
- Test the complete auth lifecycle`;

    const result = parseDecompositionResponse(response);
    expect(result.subtasks).toHaveLength(4);
    expect(result.subtasks[0].description).toBe('Research the authentication patterns used in similar projects');
  });
});

// =============================================================================
// Layer 3: Single mega-task fallback
// =============================================================================

describe('parseDecompositionResponse — mega-task fallback', () => {
  it('should create single mega-task from prose when no structure found', () => {
    const response = 'The implementation should focus on refactoring the authentication module to support multiple OAuth providers. This involves updating the token storage, adding provider-specific adapters, and ensuring backward compatibility with existing sessions.';
    const result = parseDecompositionResponse(response);
    expect(result.subtasks).toHaveLength(1);
    expect(result.subtasks[0].type).toBe('implement');
    expect(result.subtasks[0].complexity).toBe(5);
    expect(result.reasoning).toContain('mega-task');
  });

  it('should return empty for very short responses with no structure', () => {
    const result = parseDecompositionResponse('OK');
    expect(result.subtasks).toHaveLength(0);
    expect(result.parseError).toBeDefined();
  });

  it('should truncate mega-task description at ~200 chars', () => {
    const longText = 'A'.repeat(300) + ' end of text';
    const result = parseDecompositionResponse(longText);
    expect(result.subtasks).toHaveLength(1);
    expect(result.subtasks[0].description.length).toBeLessThan(210);
    expect(result.subtasks[0].description).toContain('...');
  });
});

// =============================================================================
// Combined scenarios: realistic messy LLM outputs
// =============================================================================

describe('parseDecompositionResponse — realistic messy outputs', () => {
  it('should handle glm-5 style: JSON with comments and trailing commas', () => {
    const response = `\`\`\`json
{
  // Decomposition for the given task
  "subtasks": [
    {
      "description": "Research existing code patterns",
      "type": "research",
      "complexity": 2,
      "dependencies": [],
      "parallelizable": true,
    },
    {
      "description": "Implement the feature",
      "type": "implement",
      "complexity": 5,
      "dependencies": [0],
      "parallelizable": false,
    },
  ],
  "strategy": "sequential",
  "reasoning": "Simple sequential approach",
}
\`\`\``;
    const result = parseDecompositionResponse(response);
    expect(result.subtasks).toHaveLength(2);
    expect(result.subtasks[0].description).toBe('Research existing code patterns');
  });

  it('should handle model returning Python-style dict (single quotes + True/False)', () => {
    const response = "{'subtasks': [{'description': 'Analyze codebase structure', 'type': 'research', 'complexity': 3, 'dependencies': [], 'parallelizable': true}, {'description': 'Implement parser module', 'type': 'implement', 'complexity': 6, 'dependencies': ['0'], 'parallelizable': false}], 'strategy': 'sequential', 'reasoning': 'Need research before implementation'}";
    const result = parseDecompositionResponse(response);
    expect(result.subtasks).toHaveLength(2);
  });

  it('should handle mixed prose + numbered list (JSON absent)', () => {
    const response = `Let me think about this... The task involves several steps.

I would recommend the following approach:

1. First, research the existing authentication module to understand its structure
2. Design a new token refresh mechanism that supports multiple providers
3. Implement the provider adapter interface
4. Write comprehensive tests for all OAuth flows
5. Integrate with the existing middleware chain

This should cover all the requirements.`;

    const result = parseDecompositionResponse(response);
    expect(result.subtasks).toHaveLength(5);
    expect(result.subtasks[0].type).toBe('research');
  });

  it('should handle JSON embedded in verbose explanation', () => {
    const response = `Sure! Let me decompose this task. Based on my analysis of the codebase, here's what I recommend:

\`\`\`
{"subtasks": [{"description": "Set up database models", "type": "implement", "complexity": 4, "dependencies": [], "parallelizable": false}, {"description": "Create API routes", "type": "implement", "complexity": 5, "dependencies": [0], "parallelizable": false}, {"description": "Add validation", "type": "implement", "complexity": 3, "dependencies": [1], "parallelizable": false}], "strategy": "sequential", "reasoning": "Must build layers incrementally"}
\`\`\`

This gives us a clean pipeline approach.`;

    const result = parseDecompositionResponse(response);
    expect(result.subtasks).toHaveLength(3);
    expect(result.subtasks[0].description).toBe('Set up database models');
  });

  it('should handle JSON with unquoted keys and no code block', () => {
    const response = `Here is my plan:
{subtasks: [{description: "Explore the repo", type: "research", complexity: 2, dependencies: [], parallelizable: true}, {description: "Write the code", type: "implement", complexity: 5, dependencies: [0], parallelizable: false}], strategy: "sequential"}`;

    const result = parseDecompositionResponse(response);
    expect(result.subtasks).toHaveLength(2);
  });
});
