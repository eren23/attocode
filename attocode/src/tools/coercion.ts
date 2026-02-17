/**
 * Type coercion utilities for tool parameter schemas.
 *
 * Weaker models (GLM-4, Qwen, etc.) sometimes send boolean values as strings
 * ("true"/"false") instead of actual booleans. These helpers use z.preprocess()
 * to coerce string representations into proper types before Zod validation.
 */

import { z } from 'zod';

/**
 * A boolean schema that accepts string "true"/"false" in addition to actual booleans.
 * Use this instead of z.boolean() for tool parameters that may receive string values.
 */
export function coerceBoolean() {
  return z.preprocess((val) => {
    if (typeof val === 'string') {
      const lower = val.toLowerCase().trim();
      if (lower === 'true' || lower === '1' || lower === 'yes') return true;
      if (lower === 'false' || lower === '0' || lower === 'no') return false;
    }
    return val;
  }, z.boolean());
}

/**
 * A string schema that accepts arrays by joining elements with newlines.
 * Weaker models (GLM-4, Qwen, etc.) sometimes send file content as an array
 * of lines instead of a single string. This coerces arrays into proper strings.
 */
export function coerceString() {
  return z.preprocess((val) => {
    if (Array.isArray(val)) {
      return val.map((item) => String(item)).join('\n');
    }
    return val;
  }, z.string());
}
