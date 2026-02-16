import type { TaskFailureMode } from './types.js';

export type SwarmFailureClass =
  | 'policy_blocked'
  | 'invalid_tool_args'
  | 'missing_target_path'
  | 'permission_required'
  | 'provider_spend_limit'
  | 'provider_auth'
  | 'rate_limited'
  | 'provider_transient'
  | 'timeout'
  | 'unknown';

export interface FailureClassification {
  failureClass: SwarmFailureClass;
  retryable: boolean;
  errorType: '429' | '402' | 'timeout' | 'error';
  failureMode: TaskFailureMode;
  reason: string;
}

function hasAny(haystack: string, needles: string[]): boolean {
  return needles.some((needle) => haystack.includes(needle));
}

export function classifySwarmFailure(
  rawOutput: string,
  toolCalls?: number,
): FailureClassification {
  const message = rawOutput.toLowerCase();

  if (toolCalls === -1 || hasAny(message, ['timed out', 'timeout'])) {
    return {
      failureClass: 'timeout',
      retryable: true,
      errorType: 'timeout',
      failureMode: 'timeout',
      reason: 'Worker execution timed out',
    };
  }

  if (hasAny(message, ['tool arguments could not be parsed', 'failed to parse arguments as json', 'arguments were of the wrong type or format'])) {
    return {
      failureClass: 'invalid_tool_args',
      retryable: false,
      errorType: 'error',
      failureMode: 'error',
      reason: 'Tool arguments are invalid and require prompt/task correction',
    };
  }

  if (hasAny(message, ['file not found', 'target file or directory does not exist', 'use glob to search for similar files'])) {
    return {
      failureClass: 'missing_target_path',
      retryable: false,
      errorType: 'error',
      failureMode: 'error',
      reason: 'Task references files or paths that do not exist in the workspace',
    };
  }

  if (hasAny(message, ['tool call blocked', 'policy whitelist', 'not allowed by policy'])) {
    return {
      failureClass: 'policy_blocked',
      retryable: false,
      errorType: 'error',
      failureMode: 'error',
      reason: 'Tool call blocked by policy',
    };
  }

  if (hasAny(message, ['requires approval', 'sandbox_permissions', 'require_escalated'])) {
    return {
      failureClass: 'permission_required',
      retryable: false,
      errorType: 'error',
      failureMode: 'error',
      reason: 'Action requires approval/escalation before it can run',
    };
  }

  if (hasAny(message, ['http 402', 'spend limit exceeded', 'api key usd spend limit exceeded'])) {
    return {
      failureClass: 'provider_spend_limit',
      retryable: false,
      errorType: '402',
      failureMode: 'rate-limit',
      reason: 'Provider/API key spend limit exceeded',
    };
  }

  if (hasAny(message, ['http 401', 'http 403', 'unauthorized', 'forbidden', 'invalid api key'])) {
    return {
      failureClass: 'provider_auth',
      retryable: false,
      errorType: 'error',
      failureMode: 'error',
      reason: 'Provider authentication/authorization failure',
    };
  }

  if (hasAny(message, ['http 429', 'too many requests', 'rate limit'])) {
    return {
      failureClass: 'rate_limited',
      retryable: true,
      errorType: '429',
      failureMode: 'rate-limit',
      reason: 'Provider rate limited request',
    };
  }

  if (hasAny(message, ['http 500', 'http 502', 'http 503', 'http 504', 'internal server error', 'network error'])) {
    return {
      failureClass: 'provider_transient',
      retryable: true,
      errorType: 'error',
      failureMode: 'error',
      reason: 'Transient provider/network failure',
    };
  }

  return {
    failureClass: 'unknown',
    retryable: true,
    errorType: 'error',
    failureMode: 'error',
    reason: 'Unclassified worker failure',
  };
}
