/**
 * Lesson 7: Example MCP Server
 * 
 * A simple MCP server that provides example tools.
 * Run with: npx tsx 07-mcp-integration/example-server/server.ts
 */

import * as readline from 'node:readline';

// =============================================================================
// TYPES
// =============================================================================

interface JSONRPCMessage {
  jsonrpc: '2.0';
  id?: string | number;
  method?: string;
  params?: unknown;
  result?: unknown;
  error?: { code: number; message: string };
}

interface Tool {
  name: string;
  description: string;
  inputSchema: {
    type: 'object';
    properties: Record<string, { type: string; description?: string }>;
    required?: string[];
  };
  handler: (args: Record<string, unknown>) => Promise<{ content: Array<{ type: 'text'; text: string }> }>;
}

// =============================================================================
// TOOLS
// =============================================================================

const tools: Tool[] = [
  {
    name: 'echo',
    description: 'Echo back the input message',
    inputSchema: {
      type: 'object',
      properties: {
        message: { type: 'string', description: 'Message to echo' },
      },
      required: ['message'],
    },
    handler: async (args) => ({
      content: [{ type: 'text', text: `Echo: ${args.message}` }],
    }),
  },
  {
    name: 'calculate',
    description: 'Perform basic math calculations',
    inputSchema: {
      type: 'object',
      properties: {
        operation: { type: 'string', description: 'Operation: add, subtract, multiply, divide' },
        a: { type: 'number', description: 'First number' },
        b: { type: 'number', description: 'Second number' },
      },
      required: ['operation', 'a', 'b'],
    },
    handler: async (args) => {
      const { operation, a, b } = args as { operation: string; a: number; b: number };
      let result: number;
      
      switch (operation) {
        case 'add': result = a + b; break;
        case 'subtract': result = a - b; break;
        case 'multiply': result = a * b; break;
        case 'divide': result = b !== 0 ? a / b : NaN; break;
        default:
          return { content: [{ type: 'text', text: `Unknown operation: ${operation}` }] };
      }
      
      return { content: [{ type: 'text', text: `Result: ${result}` }] };
    },
  },
  {
    name: 'get_time',
    description: 'Get the current time',
    inputSchema: {
      type: 'object',
      properties: {
        timezone: { type: 'string', description: 'Timezone (e.g., UTC, America/New_York)' },
      },
    },
    handler: async (args) => {
      const tz = (args.timezone as string) || 'UTC';
      const time = new Date().toLocaleString('en-US', { timeZone: tz });
      return { content: [{ type: 'text', text: `Current time (${tz}): ${time}` }] };
    },
  },
  {
    name: 'random_number',
    description: 'Generate a random number',
    inputSchema: {
      type: 'object',
      properties: {
        min: { type: 'number', description: 'Minimum value (default: 0)' },
        max: { type: 'number', description: 'Maximum value (default: 100)' },
      },
    },
    handler: async (args) => {
      const min = (args.min as number) ?? 0;
      const max = (args.max as number) ?? 100;
      const random = Math.floor(Math.random() * (max - min + 1)) + min;
      return { content: [{ type: 'text', text: `Random number: ${random}` }] };
    },
  },
];

// =============================================================================
// SERVER
// =============================================================================

class MCPServer {
  private rl: readline.Interface;

  constructor() {
    this.rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout,
      terminal: false,
    });
  }

  start(): void {
    this.rl.on('line', (line) => {
      this.handleMessage(line);
    });

    // Log to stderr so it doesn't interfere with JSON-RPC
    console.error('MCP Example Server started');
  }

  private async handleMessage(line: string): Promise<void> {
    try {
      const message = JSON.parse(line) as JSONRPCMessage;
      
      if (message.method) {
        const result = await this.handleMethod(message.method, message.params);
        
        if (message.id !== undefined) {
          this.respond(message.id, result);
        }
      }
    } catch (error) {
      console.error('Error handling message:', error);
    }
  }

  private async handleMethod(method: string, params: unknown): Promise<unknown> {
    switch (method) {
      case 'initialize':
        return {
          protocolVersion: '2024-11-05',
          capabilities: {
            tools: {},
          },
          serverInfo: {
            name: 'example-mcp-server',
            version: '1.0.0',
          },
        };

      case 'notifications/initialized':
        // No response needed
        return null;

      case 'tools/list':
        return {
          tools: tools.map(t => ({
            name: t.name,
            description: t.description,
            inputSchema: t.inputSchema,
          })),
        };

      case 'tools/call':
        const { name, arguments: args } = params as { name: string; arguments: Record<string, unknown> };
        const tool = tools.find(t => t.name === name);
        
        if (!tool) {
          return {
            content: [{ type: 'text', text: `Unknown tool: ${name}` }],
            isError: true,
          };
        }
        
        try {
          return await tool.handler(args);
        } catch (error) {
          return {
            content: [{ type: 'text', text: `Error: ${(error as Error).message}` }],
            isError: true,
          };
        }

      case 'resources/list':
        return { resources: [] };

      case 'prompts/list':
        return { prompts: [] };

      default:
        throw new Error(`Unknown method: ${method}`);
    }
  }

  private respond(id: string | number, result: unknown): void {
    const response: JSONRPCMessage = {
      jsonrpc: '2.0',
      id,
      result,
    };
    
    console.log(JSON.stringify(response));
  }
}

// =============================================================================
// MAIN
// =============================================================================

const server = new MCPServer();
server.start();
