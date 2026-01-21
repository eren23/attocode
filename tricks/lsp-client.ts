/**
 * Trick J: LSP Integration Basics
 *
 * Simple Language Server Protocol client for code intelligence.
 * Provides definitions, diagnostics, and completions.
 */

import { spawn, type ChildProcess } from 'child_process';
import { createInterface, type Interface as ReadlineInterface } from 'readline';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Position in a document.
 */
export interface Position {
  line: number;
  character: number;
}

/**
 * Range in a document.
 */
export interface Range {
  start: Position;
  end: Position;
}

/**
 * Location in a document.
 */
export interface Location {
  uri: string;
  range: Range;
}

/**
 * Diagnostic severity.
 */
export type DiagnosticSeverity = 'error' | 'warning' | 'information' | 'hint';

/**
 * Diagnostic message.
 */
export interface Diagnostic {
  range: Range;
  message: string;
  severity: DiagnosticSeverity;
  source?: string;
  code?: string | number;
}

/**
 * Completion item.
 */
export interface Completion {
  label: string;
  kind: CompletionKind;
  detail?: string;
  documentation?: string;
  insertText?: string;
}

/**
 * Completion item kind.
 */
export type CompletionKind =
  | 'text'
  | 'method'
  | 'function'
  | 'constructor'
  | 'field'
  | 'variable'
  | 'class'
  | 'interface'
  | 'module'
  | 'property'
  | 'keyword'
  | 'snippet';

/**
 * LSP client options.
 */
export interface LSPClientOptions {
  /** Path to language server executable */
  serverPath: string;
  /** Arguments for the server */
  serverArgs?: string[];
  /** Root URI of the workspace */
  rootUri: string;
  /** Request timeout in ms */
  timeout?: number;
}

// =============================================================================
// LSP MESSAGE TYPES
// =============================================================================

interface LSPMessage {
  jsonrpc: '2.0';
  id?: number;
  method?: string;
  params?: unknown;
  result?: unknown;
  error?: { code: number; message: string };
}

// =============================================================================
// SIMPLE LSP CLIENT
// =============================================================================

/**
 * Simple LSP client implementation.
 */
export class SimpleLSPClient {
  private process: ChildProcess | null = null;
  private readline: ReadlineInterface | null = null;
  private requestId: number = 0;
  private pending: Map<number, {
    resolve: (result: unknown) => void;
    reject: (error: Error) => void;
    timeout: NodeJS.Timeout;
  }> = new Map();
  private options: LSPClientOptions;
  private initialized: boolean = false;
  private buffer: string = '';

  constructor(options: LSPClientOptions) {
    this.options = {
      timeout: 30000,
      serverArgs: [],
      ...options,
    };
  }

  /**
   * Start the language server and initialize.
   */
  async start(): Promise<void> {
    // Spawn language server process
    this.process = spawn(this.options.serverPath, this.options.serverArgs || [], {
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    if (!this.process.stdout || !this.process.stdin) {
      throw new Error('Failed to spawn language server');
    }

    // Setup message reading
    this.process.stdout.on('data', (data: Buffer) => {
      this.handleData(data.toString());
    });

    this.process.stderr?.on('data', (data: Buffer) => {
      console.error('[LSP stderr]', data.toString());
    });

    this.process.on('exit', (code) => {
      console.log(`[LSP] Server exited with code ${code}`);
      this.initialized = false;
    });

    // Send initialize request
    const initResult = await this.request('initialize', {
      processId: process.pid,
      rootUri: this.options.rootUri,
      capabilities: {
        textDocument: {
          completion: { completionItem: { snippetSupport: true } },
          hover: {},
          definition: {},
          references: {},
          diagnostics: {},
        },
      },
    });

    // Send initialized notification
    this.notify('initialized', {});
    this.initialized = true;

    return;
  }

  /**
   * Stop the language server.
   */
  async stop(): Promise<void> {
    if (!this.process || !this.initialized) return;

    try {
      await this.request('shutdown', null);
      this.notify('exit', null);
    } catch {
      // Server might already be dead
    }

    this.process.kill();
    this.process = null;
    this.initialized = false;
  }

  /**
   * Get definition for a symbol.
   */
  async getDefinition(uri: string, line: number, character: number): Promise<Location | null> {
    const result = await this.request('textDocument/definition', {
      textDocument: { uri },
      position: { line, character },
    });

    if (!result) return null;

    // Handle array or single location
    const location = Array.isArray(result) ? result[0] : result;
    if (!location) return null;

    return {
      uri: location.uri,
      range: location.range,
    };
  }

  /**
   * Get diagnostics for a file.
   */
  async getDiagnostics(uri: string): Promise<Diagnostic[]> {
    // Diagnostics are typically pushed by the server
    // For pull-based, we'd need to request them
    // This is a simplified version

    // Notify the server about the document
    this.notify('textDocument/didOpen', {
      textDocument: {
        uri,
        languageId: this.getLanguageId(uri),
        version: 1,
        text: '', // Would need actual content
      },
    });

    // Wait for diagnostics to be published
    // In a real implementation, we'd listen for publishDiagnostics
    return [];
  }

  /**
   * Get completions at a position.
   */
  async getCompletions(uri: string, line: number, character: number): Promise<Completion[]> {
    const result = await this.request('textDocument/completion', {
      textDocument: { uri },
      position: { line, character },
    });

    if (!result) return [];

    // Handle CompletionList or Completion[]
    const items = Array.isArray(result) ? result : (result as { items?: unknown[] }).items || [];

    return items.map((item: Record<string, unknown>) => ({
      label: String(item.label || ''),
      kind: this.mapCompletionKind(item.kind as number),
      detail: item.detail as string | undefined,
      documentation:
        typeof item.documentation === 'string'
          ? item.documentation
          : (item.documentation as { value?: string })?.value,
      insertText: (item.insertText as string) || (item.label as string),
    }));
  }

  /**
   * Get hover information.
   */
  async getHover(uri: string, line: number, character: number): Promise<string | null> {
    const result = await this.request('textDocument/hover', {
      textDocument: { uri },
      position: { line, character },
    });

    if (!result) return null;

    const contents = (result as { contents?: unknown }).contents;
    if (!contents) return null;

    if (typeof contents === 'string') return contents;
    if (Array.isArray(contents)) {
      return contents
        .map((c) => (typeof c === 'string' ? c : (c as { value?: string }).value || ''))
        .join('\n');
    }
    return (contents as { value?: string }).value || null;
  }

  /**
   * Find all references to a symbol.
   */
  async getReferences(
    uri: string,
    line: number,
    character: number,
    includeDeclaration: boolean = true
  ): Promise<Location[]> {
    const result = await this.request('textDocument/references', {
      textDocument: { uri },
      position: { line, character },
      context: { includeDeclaration },
    });

    if (!result || !Array.isArray(result)) return [];

    return result.map((loc: { uri: string; range: Range }) => ({
      uri: loc.uri,
      range: loc.range,
    }));
  }

  // ===========================================================================
  // INTERNAL METHODS
  // ===========================================================================

  /**
   * Send a request and wait for response.
   */
  private async request(method: string, params: unknown): Promise<unknown> {
    if (!this.process?.stdin) {
      throw new Error('LSP server not running');
    }

    const id = ++this.requestId;
    const message: LSPMessage = {
      jsonrpc: '2.0',
      id,
      method,
      params,
    };

    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Request ${method} timed out`));
      }, this.options.timeout);

      this.pending.set(id, { resolve, reject, timeout });
      this.sendMessage(message);
    });
  }

  /**
   * Send a notification (no response expected).
   */
  private notify(method: string, params: unknown): void {
    const message: LSPMessage = {
      jsonrpc: '2.0',
      method,
      params,
    };
    this.sendMessage(message);
  }

  /**
   * Send a message to the server.
   */
  private sendMessage(message: LSPMessage): void {
    if (!this.process?.stdin) return;

    const content = JSON.stringify(message);
    const header = `Content-Length: ${Buffer.byteLength(content)}\r\n\r\n`;

    this.process.stdin.write(header + content);
  }

  /**
   * Handle incoming data from server.
   */
  private handleData(data: string): void {
    this.buffer += data;

    // Process complete messages
    while (true) {
      const headerEnd = this.buffer.indexOf('\r\n\r\n');
      if (headerEnd === -1) break;

      const header = this.buffer.slice(0, headerEnd);
      const match = header.match(/Content-Length:\s*(\d+)/i);
      if (!match) {
        this.buffer = this.buffer.slice(headerEnd + 4);
        continue;
      }

      const contentLength = parseInt(match[1], 10);
      const messageStart = headerEnd + 4;
      const messageEnd = messageStart + contentLength;

      if (this.buffer.length < messageEnd) break;

      const content = this.buffer.slice(messageStart, messageEnd);
      this.buffer = this.buffer.slice(messageEnd);

      try {
        const message = JSON.parse(content) as LSPMessage;
        this.handleMessage(message);
      } catch {
        console.error('[LSP] Failed to parse message:', content);
      }
    }
  }

  /**
   * Handle a parsed message.
   */
  private handleMessage(message: LSPMessage): void {
    if (message.id !== undefined && this.pending.has(message.id)) {
      // Response to a request
      const pending = this.pending.get(message.id)!;
      this.pending.delete(message.id);
      clearTimeout(pending.timeout);

      if (message.error) {
        pending.reject(new Error(message.error.message));
      } else {
        pending.resolve(message.result);
      }
    } else if (message.method) {
      // Notification from server
      this.handleNotification(message.method, message.params);
    }
  }

  /**
   * Handle server notification.
   */
  private handleNotification(method: string, params: unknown): void {
    // Handle known notifications
    switch (method) {
      case 'textDocument/publishDiagnostics':
        // Could emit event here
        break;
      case 'window/logMessage':
        const logParams = params as { type: number; message: string };
        console.log(`[LSP ${logParams.type}] ${logParams.message}`);
        break;
    }
  }

  /**
   * Get language ID from URI.
   */
  private getLanguageId(uri: string): string {
    const ext = uri.split('.').pop()?.toLowerCase();
    const map: Record<string, string> = {
      ts: 'typescript',
      tsx: 'typescriptreact',
      js: 'javascript',
      jsx: 'javascriptreact',
      py: 'python',
      rs: 'rust',
      go: 'go',
      java: 'java',
      rb: 'ruby',
      c: 'c',
      cpp: 'cpp',
      h: 'c',
      hpp: 'cpp',
    };
    return map[ext || ''] || 'plaintext';
  }

  /**
   * Map completion kind number to string.
   */
  private mapCompletionKind(kind: number): CompletionKind {
    const map: Record<number, CompletionKind> = {
      1: 'text',
      2: 'method',
      3: 'function',
      4: 'constructor',
      5: 'field',
      6: 'variable',
      7: 'class',
      8: 'interface',
      9: 'module',
      10: 'property',
      14: 'keyword',
      15: 'snippet',
    };
    return map[kind] || 'text';
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createLSPClient(options: LSPClientOptions): SimpleLSPClient {
  return new SimpleLSPClient(options);
}

// Usage:
// const client = createLSPClient({
//   serverPath: 'typescript-language-server',
//   serverArgs: ['--stdio'],
//   rootUri: 'file:///path/to/project',
// });
//
// await client.start();
//
// const definition = await client.getDefinition('file:///path/to/file.ts', 10, 5);
// console.log('Definition:', definition);
//
// const completions = await client.getCompletions('file:///path/to/file.ts', 10, 5);
// console.log('Completions:', completions.slice(0, 5));
//
// await client.stop();
