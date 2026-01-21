/**
 * Trick L: Sortable IDs
 *
 * Generate K-sortable unique identifiers that are:
 * - Chronologically sortable (timestamp prefix)
 * - Collision-resistant (random suffix)
 * - URL-safe and compact
 *
 * Inspired by ULID, KSUID, and similar schemes.
 *
 * Usage:
 *   const id = generateId();           // "01HN5X2Y3Z-abc123"
 *   const id = generateId('msg');      // "msg_01HN5X2Y3Z-abc123"
 *   const ids = [id1, id2, id3].sort(); // Chronological order!
 */

// =============================================================================
// CONSTANTS
// =============================================================================

const BASE32_CHARS = '0123456789abcdefghjkmnpqrstvwxyz';
const RANDOM_CHARS = 'abcdefghijklmnopqrstuvwxyz0123456789';

// =============================================================================
// CORE FUNCTIONS
// =============================================================================

/**
 * Generate a sortable unique ID.
 *
 * Format: [prefix_]<timestamp>-<random>
 * - timestamp: Base32-encoded milliseconds (10 chars)
 * - random: 6 random alphanumeric chars
 */
export function generateId(prefix?: string): string {
  const timestamp = encodeTimestamp(Date.now());
  const random = generateRandom(6);
  const id = `${timestamp}-${random}`;
  return prefix ? `${prefix}_${id}` : id;
}

/**
 * Generate a batch of sequential IDs.
 * Uses same timestamp for all, different random suffixes.
 */
export function generateBatch(count: number, prefix?: string): string[] {
  const timestamp = encodeTimestamp(Date.now());
  const ids: string[] = [];

  for (let i = 0; i < count; i++) {
    const random = generateRandom(6);
    const id = `${timestamp}-${random}`;
    ids.push(prefix ? `${prefix}_${id}` : id);
  }

  return ids;
}

/**
 * Extract timestamp from an ID.
 */
export function getTimestamp(id: string): Date | null {
  // Remove prefix if present
  const parts = id.split('_');
  const idPart = parts.length > 1 ? parts[parts.length - 1] : id;

  // Extract timestamp portion (before the dash)
  const timestampPart = idPart.split('-')[0];
  if (!timestampPart || timestampPart.length !== 10) {
    return null;
  }

  const ms = decodeTimestamp(timestampPart);
  return ms !== null ? new Date(ms) : null;
}

/**
 * Compare two IDs chronologically.
 * Returns negative if a < b, positive if a > b, 0 if equal.
 */
export function compareIds(a: string, b: string): number {
  // Simple string comparison works due to sortable encoding
  return a.localeCompare(b);
}

/**
 * Check if an ID was generated after a certain time.
 */
export function isAfter(id: string, date: Date): boolean {
  const timestamp = getTimestamp(id);
  return timestamp !== null && timestamp > date;
}

/**
 * Check if an ID was generated before a certain time.
 */
export function isBefore(id: string, date: Date): boolean {
  const timestamp = getTimestamp(id);
  return timestamp !== null && timestamp < date;
}

// =============================================================================
// ENCODING
// =============================================================================

/**
 * Encode a timestamp as a 10-character base32 string.
 */
function encodeTimestamp(ms: number): string {
  let result = '';
  let remaining = ms;

  // Encode to base32, 10 chars gives us ~35 years of unique timestamps
  for (let i = 0; i < 10; i++) {
    const index = remaining % 32;
    result = BASE32_CHARS[index] + result;
    remaining = Math.floor(remaining / 32);
  }

  return result;
}

/**
 * Decode a base32 timestamp string to milliseconds.
 */
function decodeTimestamp(encoded: string): number | null {
  if (encoded.length !== 10) return null;

  let result = 0;
  for (let i = 0; i < encoded.length; i++) {
    const char = encoded[i];
    const index = BASE32_CHARS.indexOf(char);
    if (index === -1) return null;
    result = result * 32 + index;
  }

  return result;
}

/**
 * Generate random alphanumeric string.
 */
function generateRandom(length: number): string {
  let result = '';
  for (let i = 0; i < length; i++) {
    const index = Math.floor(Math.random() * RANDOM_CHARS.length);
    result += RANDOM_CHARS[index];
  }
  return result;
}

// =============================================================================
// ID FACTORIES
// =============================================================================

/**
 * Create an ID generator with a fixed prefix.
 */
export function createIdGenerator(prefix: string): () => string {
  return () => generateId(prefix);
}

/**
 * Common prefixed ID generators.
 */
export const idGenerators = {
  message: createIdGenerator('msg'),
  thread: createIdGenerator('thd'),
  checkpoint: createIdGenerator('ckpt'),
  grant: createIdGenerator('grant'),
  session: createIdGenerator('sess'),
  agent: createIdGenerator('agt'),
  task: createIdGenerator('task'),
  trace: createIdGenerator('trace'),
  span: createIdGenerator('span'),
};

// =============================================================================
// VALIDATION
// =============================================================================

/**
 * Validate ID format.
 */
export function isValidId(id: string, prefix?: string): boolean {
  if (prefix) {
    if (!id.startsWith(`${prefix}_`)) return false;
    id = id.slice(prefix.length + 1);
  }

  // Should be timestamp-random format
  const parts = id.split('-');
  if (parts.length !== 2) return false;

  const [timestamp, random] = parts;
  if (timestamp.length !== 10 || random.length !== 6) return false;

  // Validate timestamp chars
  for (const char of timestamp) {
    if (!BASE32_CHARS.includes(char)) return false;
  }

  // Validate random chars
  for (const char of random) {
    if (!RANDOM_CHARS.includes(char)) return false;
  }

  return true;
}

/**
 * Parse an ID into its components.
 */
export function parseId(id: string): {
  prefix?: string;
  timestamp: Date | null;
  random: string;
} | null {
  const parts = id.split('_');
  const prefix = parts.length > 1 ? parts.slice(0, -1).join('_') : undefined;
  const idPart = parts[parts.length - 1];

  const [timestampPart, random] = idPart.split('-');
  if (!timestampPart || !random) return null;

  const timestamp = getTimestamp(id);

  return { prefix, timestamp, random };
}
