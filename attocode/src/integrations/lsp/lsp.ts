/**
 * LSP Integration
 *
 * Language Server Protocol client manager for code intelligence.
 * Provides definitions, completions, hover info, and references.
 * Wraps and extends the SimpleLSPClient from tricks/lsp-client.ts.
 *
 * Usage:
 *   const lsp = createLSPManager({ autoDetect: true });
 *   await lsp.autoStart('/path/to/project');
 *   const def = await lsp.getDefinition('file.ts', 10, 5);
 */

import { spawn, type ChildProcess } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { logger } from '../utilities/logger.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Position in a document (0-indexed).
 */
export interface LSPPosition {
  line: number;
  character: number;
}

/**
 * Range in a document.
 */
export interface LSPRange {
  start: LSPPosition;
  end: LSPPosition;
}

/**
 * Location in a document.
 */
export interface LSPLocation {
  uri: string;
  range: LSPRange;
}

/**
 * Diagnostic severity.
 */
export type DiagnosticSeverity = 'error' | 'warning' | 'information' | 'hint';

/**
 * Diagnostic message.
 */
export interface LSPDiagnostic {
  range: LSPRange;
  message: string;
  severity: DiagnosticSeverity;
  source?: string;
  code?: string | number;
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
 * Completion item.
 */
export interface LSPCompletion {
  label: string;
  kind: CompletionKind;
  detail?: string;
  documentation?: string;
  insertText?: string;
}

/**
 * Language server configuration.
 */
export interface LanguageServerConfig {
  /** Command to start the server */
  command: string;
  /** Arguments for the server */
  args?: string[];
  /** File extensions this server handles */
  extensions: string[];
  /** Language ID for the server */
  languageId: string;
}

/**
 * LSP manager configuration.
 */
export interface LSPConfig {
  /** Enable/disable LSP support */
  enabled?: boolean;
  /** Custom server configurations */
  servers?: Record<string, LanguageServerConfig>;
  /** Auto-detect and start servers based on file types */
  autoDetect?: boolean;
  /** Request timeout in ms */
  timeout?: number;
  /** Root URI of the workspace */
  rootUri?: string;
}

/**
 * LSP event types.
 */
export type LSPEvent =
  | { type: 'lsp.started'; languageId: string; command: string }
  | { type: 'lsp.stopped'; languageId: string }
  | { type: 'lsp.error'; languageId: string; error: string }
  | { type: 'lsp.diagnostics'; uri: string; diagnostics: LSPDiagnostic[] };

export type LSPEventListener = (event: LSPEvent) => void;

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
// BUILT-IN SERVER CONFIGS
// =============================================================================

const BUILTIN_SERVERS: Record<string, LanguageServerConfig> = {
  typescript: {
    command: 'typescript-language-server',
    args: ['--stdio'],
    extensions: ['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs'],
    languageId: 'typescript',
  },
  python: {
    command: 'pyright-langserver',
    args: ['--stdio'],
    extensions: ['.py', '.pyi'],
    languageId: 'python',
  },
  rust: {
    command: 'rust-analyzer',
    args: [],
    extensions: ['.rs'],
    languageId: 'rust',
  },
  go: {
    command: 'gopls',
    args: [],
    extensions: ['.go'],
    languageId: 'go',
  },
  json: {
    command: 'vscode-json-language-server',
    args: ['--stdio'],
    extensions: ['.json', '.jsonc'],
    languageId: 'json',
  },
};

// =============================================================================
// LSP CLIENT (Internal)
// =============================================================================

class LSPClient {
  private process: ChildProcess | null = null;
  private requestId: number = 0;
  private pending: Map<
    number,
    {
      resolve: (result: unknown) => void;
      reject: (error: Error) => void;
      timeout: NodeJS.Timeout;
    }
  > = new Map();
  private buffer: string = '';
  private initialized: boolean = false;
  private config: LanguageServerConfig;
  private rootUri: string;
  private timeout: number;
  private onDiagnostics?: (uri: string, diagnostics: LSPDiagnostic[]) => void;

  constructor(
    config: LanguageServerConfig,
    rootUri: string,
    timeout: number = 30000,
    onDiagnostics?: (uri: string, diagnostics: LSPDiagnostic[]) => void,
  ) {
    this.config = config;
    this.rootUri = rootUri;
    this.timeout = timeout;
    this.onDiagnostics = onDiagnostics;
  }

  get languageId(): string {
    return this.config.languageId;
  }

  get isInitialized(): boolean {
    return this.initialized;
  }

  async start(): Promise<void> {
    this.process = spawn(this.config.command, this.config.args || [], {
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    if (!this.process.stdout || !this.process.stdin) {
      throw new Error(`Failed to spawn ${this.config.command}`);
    }

    this.process.stdout.on('data', (data: Buffer) => {
      this.handleData(data.toString());
    });

    this.process.stderr?.on('data', (data: Buffer) => {
      // Log but don't fail on stderr
      logger.debug(`[LSP ${this.config.languageId}] ${data.toString().trim()}`);
    });

    this.process.on('exit', (code) => {
      this.initialized = false;
      logger.debug(`[LSP ${this.config.languageId}] exited with code ${code}`);
    });

    this.process.on('error', (err) => {
      logger.error(`[LSP ${this.config.languageId}] error:`, { error: err.message });
    });

    // Initialize
    await this.request('initialize', {
      processId: process.pid,
      rootUri: this.rootUri,
      capabilities: {
        textDocument: {
          completion: { completionItem: { snippetSupport: true } },
          hover: {},
          definition: {},
          references: {},
          publishDiagnostics: {},
        },
      },
    });

    this.notify('initialized', {});
    this.initialized = true;
  }

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

  async getDefinition(uri: string, line: number, character: number): Promise<LSPLocation | null> {
    if (!this.initialized) return null;

    const result = await this.request('textDocument/definition', {
      textDocument: { uri },
      position: { line, character },
    });

    if (!result) return null;

    const location = Array.isArray(result) ? result[0] : result;
    if (!location) return null;

    return {
      uri: (location as { uri: string }).uri,
      range: (location as { range: LSPRange }).range,
    };
  }

  async getCompletions(uri: string, line: number, character: number): Promise<LSPCompletion[]> {
    if (!this.initialized) return [];

    const result = await this.request('textDocument/completion', {
      textDocument: { uri },
      position: { line, character },
    });

    if (!result) return [];

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

  async getHover(uri: string, line: number, character: number): Promise<string | null> {
    if (!this.initialized) return null;

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

  async getReferences(
    uri: string,
    line: number,
    character: number,
    includeDeclaration: boolean = true,
  ): Promise<LSPLocation[]> {
    if (!this.initialized) return [];

    const result = await this.request('textDocument/references', {
      textDocument: { uri },
      position: { line, character },
      context: { includeDeclaration },
    });

    if (!result || !Array.isArray(result)) return [];

    return result.map((loc: { uri: string; range: LSPRange }) => ({
      uri: loc.uri,
      range: loc.range,
    }));
  }

  // Notify server about file open/change
  notifyDocumentOpen(uri: string, text: string): void {
    if (!this.initialized) return;

    this.notify('textDocument/didOpen', {
      textDocument: {
        uri,
        languageId: this.config.languageId,
        version: 1,
        text,
      },
    });
  }

  notifyDocumentChange(uri: string, text: string, version: number): void {
    if (!this.initialized) return;

    this.notify('textDocument/didChange', {
      textDocument: { uri, version },
      contentChanges: [{ text }],
    });
  }

  notifyDocumentClose(uri: string): void {
    if (!this.initialized) return;

    this.notify('textDocument/didClose', {
      textDocument: { uri },
    });
  }

  // Internal methods
  private async request(method: string, params: unknown): Promise<unknown> {
    if (!this.process?.stdin) {
      throw new Error('LSP server not running');
    }

    const id = ++this.requestId;
    const message: LSPMessage = { jsonrpc: '2.0', id, method, params };

    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Request ${method} timed out`));
      }, this.timeout);

      this.pending.set(id, { resolve, reject, timeout });
      this.sendMessage(message);
    });
  }

  private notify(method: string, params: unknown): void {
    const message: LSPMessage = { jsonrpc: '2.0', method, params };
    this.sendMessage(message);
  }

  private sendMessage(message: LSPMessage): void {
    if (!this.process?.stdin) return;

    const content = JSON.stringify(message);
    const header = `Content-Length: ${Buffer.byteLength(content)}\r\n\r\n`;

    this.process.stdin.write(header + content);
  }

  private handleData(data: string): void {
    this.buffer += data;

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
        logger.error('[LSP] Failed to parse message');
      }
    }
  }

  private handleMessage(message: LSPMessage): void {
    if (message.id !== undefined && this.pending.has(message.id)) {
      const pending = this.pending.get(message.id)!;
      this.pending.delete(message.id);
      clearTimeout(pending.timeout);

      if (message.error) {
        pending.reject(new Error(message.error.message));
      } else {
        pending.resolve(message.result);
      }
    } else if (message.method) {
      this.handleNotification(message.method, message.params);
    }
  }

  private handleNotification(method: string, params: unknown): void {
    if (method === 'textDocument/publishDiagnostics' && this.onDiagnostics) {
      const p = params as { uri: string; diagnostics: LSPDiagnostic[] };
      this.onDiagnostics(p.uri, p.diagnostics);
    }
  }

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
// LSP MANAGER
// =============================================================================

/**
 * Manages multiple LSP clients for different languages.
 */
export class LSPManager {
  private clients: Map<string, LSPClient> = new Map();
  private config: Required<LSPConfig>;
  private eventListeners: Set<LSPEventListener> = new Set();
  private diagnosticsCache: Map<string, LSPDiagnostic[]> = new Map();

  constructor(config: LSPConfig = {}) {
    this.config = {
      enabled: config.enabled ?? true,
      servers: { ...BUILTIN_SERVERS, ...config.servers },
      autoDetect: config.autoDetect ?? true,
      timeout: config.timeout ?? 30000,
      rootUri: config.rootUri ?? `file://${process.cwd()}`,
    };
  }

  /**
   * Auto-detect and start LSP servers based on project files.
   */
  async autoStart(workspaceRoot?: string): Promise<string[]> {
    if (!this.config.enabled || !this.config.autoDetect) {
      return [];
    }

    const rootUri = workspaceRoot ? `file://${workspaceRoot}` : this.config.rootUri;
    const rootPath = workspaceRoot || process.cwd();

    // Detect which languages are present
    const detectedLanguages = await this.detectLanguages(rootPath);
    const started: string[] = [];

    for (const languageId of detectedLanguages) {
      try {
        await this.startServer(languageId, rootUri);
        started.push(languageId);
      } catch (err) {
        // Server might not be installed, that's OK
        this.emit({
          type: 'lsp.error',
          languageId,
          error: err instanceof Error ? err.message : String(err),
        });
      }
    }

    return started;
  }

  /**
   * Start a specific language server.
   */
  async startServer(languageId: string, rootUri?: string): Promise<void> {
    if (this.clients.has(languageId)) {
      return; // Already running
    }

    const serverConfig = this.config.servers[languageId];
    if (!serverConfig) {
      throw new Error(`No server configuration for language: ${languageId}`);
    }

    // Check if command exists
    const exists = await this.commandExists(serverConfig.command);
    if (!exists) {
      throw new Error(`Language server not found: ${serverConfig.command}`);
    }

    const client = new LSPClient(
      serverConfig,
      rootUri || this.config.rootUri,
      this.config.timeout,
      (uri, diagnostics) => {
        this.diagnosticsCache.set(uri, diagnostics);
        this.emit({ type: 'lsp.diagnostics', uri, diagnostics });
      },
    );

    await client.start();
    this.clients.set(languageId, client);
    this.emit({ type: 'lsp.started', languageId, command: serverConfig.command });
  }

  /**
   * Stop a specific language server.
   */
  async stopServer(languageId: string): Promise<void> {
    const client = this.clients.get(languageId);
    if (!client) return;

    await client.stop();
    this.clients.delete(languageId);
    this.emit({ type: 'lsp.stopped', languageId });
  }

  /**
   * Stop all language servers.
   */
  async stopAll(): Promise<void> {
    const stopPromises = Array.from(this.clients.keys()).map((id) => this.stopServer(id));
    await Promise.all(stopPromises);
  }

  /**
   * Get definition for a symbol.
   */
  async getDefinition(file: string, line: number, col: number): Promise<LSPLocation | null> {
    const client = this.getClientForFile(file);
    if (!client) return null;

    const uri = file.startsWith('file://') ? file : `file://${path.resolve(file)}`;
    return client.getDefinition(uri, line, col);
  }

  /**
   * Get completions at a position.
   */
  async getCompletions(file: string, line: number, col: number): Promise<LSPCompletion[]> {
    const client = this.getClientForFile(file);
    if (!client) return [];

    const uri = file.startsWith('file://') ? file : `file://${path.resolve(file)}`;
    return client.getCompletions(uri, line, col);
  }

  /**
   * Get hover information.
   */
  async getHover(file: string, line: number, col: number): Promise<string | null> {
    const client = this.getClientForFile(file);
    if (!client) return null;

    const uri = file.startsWith('file://') ? file : `file://${path.resolve(file)}`;
    return client.getHover(uri, line, col);
  }

  /**
   * Get all references to a symbol.
   */
  async getReferences(
    file: string,
    line: number,
    col: number,
    includeDeclaration: boolean = true,
  ): Promise<LSPLocation[]> {
    const client = this.getClientForFile(file);
    if (!client) return [];

    const uri = file.startsWith('file://') ? file : `file://${path.resolve(file)}`;
    return client.getReferences(uri, line, col, includeDeclaration);
  }

  /**
   * Get cached diagnostics for a file.
   */
  getDiagnostics(file: string): LSPDiagnostic[] {
    const uri = file.startsWith('file://') ? file : `file://${path.resolve(file)}`;
    return this.diagnosticsCache.get(uri) || [];
  }

  /**
   * Notify about a file being opened.
   */
  notifyFileOpened(file: string, content: string): void {
    const client = this.getClientForFile(file);
    if (!client) return;

    const uri = file.startsWith('file://') ? file : `file://${path.resolve(file)}`;
    client.notifyDocumentOpen(uri, content);
  }

  /**
   * Notify about a file being changed.
   */
  notifyFileChanged(file: string, content: string, version: number = 1): void {
    const client = this.getClientForFile(file);
    if (!client) return;

    const uri = file.startsWith('file://') ? file : `file://${path.resolve(file)}`;
    client.notifyDocumentChange(uri, content, version);
  }

  /**
   * Notify about a file being closed.
   */
  notifyFileClosed(file: string): void {
    const client = this.getClientForFile(file);
    if (!client) return;

    const uri = file.startsWith('file://') ? file : `file://${path.resolve(file)}`;
    client.notifyDocumentClose(uri);
  }

  /**
   * Get list of active language servers.
   */
  getActiveServers(): string[] {
    return Array.from(this.clients.keys());
  }

  /**
   * Check if a language server is running.
   */
  isServerRunning(languageId: string): boolean {
    const client = this.clients.get(languageId);
    return client?.isInitialized ?? false;
  }

  /**
   * Subscribe to LSP events.
   */
  subscribe(listener: LSPEventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  /**
   * Cleanup all resources.
   */
  async cleanup(): Promise<void> {
    await this.stopAll();
    this.eventListeners.clear();
    this.diagnosticsCache.clear();
  }

  // Internal helpers

  private getClientForFile(file: string): LSPClient | null {
    const ext = path.extname(file).toLowerCase();

    for (const [languageId, serverConfig] of Object.entries(this.config.servers)) {
      if (serverConfig.extensions.includes(ext)) {
        return this.clients.get(languageId) || null;
      }
    }

    return null;
  }

  private async detectLanguages(rootPath: string): Promise<string[]> {
    const detected: Set<string> = new Set();

    // Quick scan of common files
    const checkFiles = [
      { file: 'package.json', language: 'typescript' },
      { file: 'tsconfig.json', language: 'typescript' },
      { file: 'pyproject.toml', language: 'python' },
      { file: 'requirements.txt', language: 'python' },
      { file: 'Cargo.toml', language: 'rust' },
      { file: 'go.mod', language: 'go' },
    ];

    for (const { file, language } of checkFiles) {
      if (fs.existsSync(path.join(rootPath, file))) {
        detected.add(language);
      }
    }

    return Array.from(detected);
  }

  private async commandExists(command: string): Promise<boolean> {
    return new Promise((resolve) => {
      const proc = spawn('which', [command], { stdio: 'ignore' });
      proc.on('close', (code) => resolve(code === 0));
      proc.on('error', () => resolve(false));
    });
  }

  private emit(event: LSPEvent): void {
    for (const listener of this.eventListeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create an LSP manager.
 */
export function createLSPManager(config?: LSPConfig): LSPManager {
  return new LSPManager(config);
}

/**
 * Create an LSP manager and auto-start servers.
 */
export async function createAndStartLSPManager(
  workspaceRoot?: string,
  config?: LSPConfig,
): Promise<LSPManager> {
  const manager = new LSPManager(config);
  await manager.autoStart(workspaceRoot);
  return manager;
}
