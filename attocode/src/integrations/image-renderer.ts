/**
 * Image Renderer
 *
 * Renders images inline in the terminal using the best available protocol.
 * Supports Kitty, iTerm2/WezTerm, and falls back to block characters.
 *
 * @example
 * ```typescript
 * const renderer = createImageRenderer();
 * await renderer.renderFile('/path/to/image.png');
 * ```
 */

import { readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { extname } from 'node:path';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Supported terminal image protocols.
 */
export type ImageProtocol = 'kitty' | 'iterm' | 'sixel' | 'block' | 'none';

/**
 * Image renderer configuration.
 */
export interface ImageRendererConfig {
  /** Force a specific protocol (default: auto-detect) */
  protocol?: ImageProtocol | 'auto';
  /** Maximum width in cells (default: 80) */
  maxWidth?: number;
  /** Maximum height in cells (default: 24) */
  maxHeight?: number;
  /** Preserve aspect ratio (default: true) */
  preserveAspectRatio?: boolean;
}

/**
 * Image rendering result.
 */
export interface ImageRenderResult {
  /** The escape sequence or text to display */
  output: string;
  /** Protocol used for rendering */
  protocol: ImageProtocol;
  /** Whether rendering was successful */
  success: boolean;
  /** Error message if failed */
  error?: string;
}

/**
 * Supported image formats.
 */
const SUPPORTED_FORMATS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp']);

// =============================================================================
// PROTOCOL DETECTION
// =============================================================================

/**
 * Detect the best available image protocol for the current terminal.
 */
export function detectProtocol(): ImageProtocol {
  const env = process.env;

  // Kitty terminal
  if (env.KITTY_WINDOW_ID) {
    return 'kitty';
  }

  // iTerm2 (also used by WezTerm)
  if (env.ITERM_SESSION_ID || env.TERM_PROGRAM === 'iTerm.app') {
    return 'iterm';
  }

  // WezTerm (uses iTerm protocol)
  if (env.TERM_PROGRAM === 'WezTerm') {
    return 'iterm';
  }

  // Check for sixel support via TERM
  if (env.TERM && (
    env.TERM.includes('sixel') ||
    env.TERM === 'xterm' ||
    env.TERM === 'xterm-256color'
  )) {
    // Note: Sixel detection is imperfect; many terminals don't advertise it
    return 'sixel';
  }

  // Fall back to block characters
  return 'block';
}

/**
 * Check if a protocol is available.
 */
export function isProtocolAvailable(protocol: ImageProtocol): boolean {
  const detected = detectProtocol();

  if (protocol === 'block') return true;
  if (protocol === 'none') return true;
  if (protocol === detected) return true;

  // Kitty protocol requires Kitty terminal
  if (protocol === 'kitty') return detected === 'kitty';

  // iTerm protocol works in iTerm2 and WezTerm
  if (protocol === 'iterm') return detected === 'iterm';

  // Sixel is harder to detect reliably
  if (protocol === 'sixel') return detected === 'sixel';

  return false;
}

// =============================================================================
// IMAGE RENDERER
// =============================================================================

/**
 * Image renderer class.
 */
export class ImageRenderer {
  private config: Required<ImageRendererConfig>;
  private protocol: ImageProtocol;

  constructor(config: ImageRendererConfig = {}) {
    this.config = {
      protocol: config.protocol ?? 'auto',
      maxWidth: config.maxWidth ?? 80,
      maxHeight: config.maxHeight ?? 24,
      preserveAspectRatio: config.preserveAspectRatio ?? true,
    };

    this.protocol = this.config.protocol === 'auto'
      ? detectProtocol()
      : this.config.protocol;
  }

  /**
   * Get the current protocol.
   */
  getProtocol(): ImageProtocol {
    return this.protocol;
  }

  /**
   * Check if image rendering is supported.
   */
  isSupported(): boolean {
    return this.protocol !== 'none';
  }

  /**
   * Check if a file is a supported image format.
   */
  isSupportedFormat(filePath: string): boolean {
    const ext = extname(filePath).toLowerCase();
    return SUPPORTED_FORMATS.has(ext);
  }

  /**
   * Render an image from a file path.
   */
  async renderFile(filePath: string): Promise<ImageRenderResult> {
    if (!existsSync(filePath)) {
      return {
        output: '',
        protocol: this.protocol,
        success: false,
        error: `File not found: ${filePath}`,
      };
    }

    if (!this.isSupportedFormat(filePath)) {
      return {
        output: '',
        protocol: this.protocol,
        success: false,
        error: `Unsupported image format: ${extname(filePath)}`,
      };
    }

    try {
      const data = await readFile(filePath);
      return this.renderBuffer(data, filePath);
    } catch (err) {
      return {
        output: '',
        protocol: this.protocol,
        success: false,
        error: `Failed to read file: ${(err as Error).message}`,
      };
    }
  }

  /**
   * Render an image from a buffer.
   */
  async renderBuffer(data: Buffer, filename?: string): Promise<ImageRenderResult> {
    switch (this.protocol) {
      case 'kitty':
        return this.renderKitty(data);
      case 'iterm':
        return this.renderITerm(data, filename);
      case 'sixel':
        return this.renderSixel(data);
      case 'block':
        return this.renderBlock(data);
      case 'none':
        return {
          output: '[Image display not supported in this terminal]',
          protocol: 'none',
          success: false,
          error: 'No image protocol available',
        };
    }
  }

  /**
   * Render using Kitty graphics protocol.
   * @see https://sw.kovidgoyal.net/kitty/graphics-protocol/
   */
  private renderKitty(data: Buffer): ImageRenderResult {
    const base64 = data.toString('base64');
    const chunks: string[] = [];

    // Split into 4096-byte chunks for transmission
    const chunkSize = 4096;
    for (let i = 0; i < base64.length; i += chunkSize) {
      const chunk = base64.slice(i, i + chunkSize);
      const isLast = i + chunkSize >= base64.length;

      // Kitty graphics protocol escape sequence
      // a=T (transmit), f=100 (PNG), m=0/1 (more chunks coming)
      const params = i === 0
        ? `a=T,f=100,m=${isLast ? 0 : 1}`
        : `m=${isLast ? 0 : 1}`;

      chunks.push(`\x1b_G${params};${chunk}\x1b\\`);
    }

    return {
      output: chunks.join(''),
      protocol: 'kitty',
      success: true,
    };
  }

  /**
   * Render using iTerm2 inline images protocol.
   * @see https://iterm2.com/documentation-images.html
   */
  private renderITerm(data: Buffer, filename?: string): ImageRenderResult {
    const base64 = data.toString('base64');

    // iTerm2 inline image format
    // name=<base64 filename>, size=<bytes>, width=auto, height=auto, inline=1
    const name = filename ? Buffer.from(filename).toString('base64') : '';
    const params = [
      `name=${name}`,
      `size=${data.length}`,
      `width=${this.config.maxWidth}`,
      `height=${this.config.maxHeight}`,
      `preserveAspectRatio=${this.config.preserveAspectRatio ? 1 : 0}`,
      'inline=1',
    ].join(';');

    const output = `\x1b]1337;File=${params}:${base64}\x07`;

    return {
      output,
      protocol: 'iterm',
      success: true,
    };
  }

  /**
   * Render using Sixel graphics (limited support).
   * This is a stub - full sixel encoding is complex.
   */
  private renderSixel(_data: Buffer): ImageRenderResult {
    // Sixel encoding is complex and requires image processing
    // Fall back to block rendering for now
    return {
      output: '[Sixel rendering not implemented - install terminal-image for fallback]',
      protocol: 'sixel',
      success: false,
      error: 'Sixel encoding not implemented',
    };
  }

  /**
   * Render using block characters (fallback).
   * Uses terminal-image if available.
   */
  private async renderBlock(data: Buffer): Promise<ImageRenderResult> {
    try {
      // Dynamic import to avoid bundling issues
      const terminalImage = await import('terminal-image');

      const output = await terminalImage.default.buffer(data, {
        width: this.config.maxWidth,
        height: this.config.maxHeight,
        preserveAspectRatio: this.config.preserveAspectRatio,
      });

      return {
        output,
        protocol: 'block',
        success: true,
      };
    } catch (err) {
      return {
        output: '[Image: terminal-image package not available]',
        protocol: 'block',
        success: false,
        error: `Block rendering failed: ${(err as Error).message}`,
      };
    }
  }

  /**
   * Render an image with a caption.
   */
  async renderWithCaption(
    filePath: string,
    caption?: string
  ): Promise<string> {
    const result = await this.renderFile(filePath);

    const lines: string[] = [];

    if (result.success) {
      lines.push(result.output);
    } else {
      lines.push(`[Image: ${result.error}]`);
    }

    if (caption) {
      lines.push(`  ${caption}`);
    }

    return lines.join('\n');
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create an image renderer with auto-detected protocol.
 */
export function createImageRenderer(config?: ImageRendererConfig): ImageRenderer {
  return new ImageRenderer(config);
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Get protocol info for display.
 */
export function getProtocolInfo(): {
  detected: ImageProtocol;
  terminal: string | undefined;
  supported: boolean;
} {
  const detected = detectProtocol();
  const terminal = process.env.TERM_PROGRAM || process.env.TERM;

  return {
    detected,
    terminal,
    supported: detected !== 'none',
  };
}

/**
 * Check if a file can be rendered as an image.
 */
export function canRenderImage(filePath: string): boolean {
  const ext = extname(filePath).toLowerCase();
  return SUPPORTED_FORMATS.has(ext);
}
