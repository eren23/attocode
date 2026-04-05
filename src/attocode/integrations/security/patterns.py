"""Security scanning pattern definitions.

High-confidence patterns for secret detection and code anti-pattern
recognition, each tagged with a CWE ID and severity level.

NOTE: The regex patterns in this file are DETECTORS — they match
dangerous constructs in scanned code to flag them for review.
The patterns themselves do not execute any dangerous operations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Category(StrEnum):
    SECRET = "secret"
    ANTI_PATTERN = "anti_pattern"
    DEPENDENCY = "dependency"


@dataclass(slots=True)
class SecurityPattern:
    """A single security scanning pattern."""

    name: str
    pattern: re.Pattern[str]
    severity: Severity
    category: Category
    cwe_id: str
    message: str
    recommendation: str
    languages: list[str] = field(default_factory=list)  # empty = all languages
    scan_comments: bool = False  # if True, scan comment lines too (for stego payloads)


# ---------------------------------------------------------------------------
# Secret detection patterns
# ---------------------------------------------------------------------------

_SECRET_DEFS: list[tuple[str, str, str, str, str, str]] = [
    # (name, regex, severity, cwe, message, recommendation)
    ("generic_api_key",
     r"""(?:api[_-]?key|apikey)\s*[:=]\s*['"]([a-zA-Z0-9_\-]{20,})['"]""",
     "high", "CWE-798",
     "Hardcoded API key detected",
     "Use environment variables or a secrets manager"),
    ("openai_key",
     r"""sk-(?:proj-)?[a-zA-Z0-9_-]{20,}""",
     "critical", "CWE-798",
     "OpenAI API key (sk-...) detected",
     "Move to OPENAI_API_KEY environment variable"),
    ("anthropic_key",
     r"""sk-ant-[a-zA-Z0-9\-]{20,}""",
     "critical", "CWE-798",
     "Anthropic API key (sk-ant-...) detected",
     "Move to ANTHROPIC_API_KEY environment variable"),
    ("github_token",
     r"""ghp_[a-zA-Z0-9]{36}""",
     "critical", "CWE-798",
     "GitHub personal access token detected",
     "Use GITHUB_TOKEN environment variable"),
    ("github_oauth",
     r"""gho_[a-zA-Z0-9]{36}""",
     "high", "CWE-798",
     "GitHub OAuth token detected",
     "Use environment variable or OAuth flow"),
    ("aws_access_key",
     r"""AKIA[0-9A-Z]{16}""",
     "critical", "CWE-798",
     "AWS access key ID detected",
     "Use IAM roles or AWS_ACCESS_KEY_ID env var"),
    ("aws_secret_key",
     r"""(?:aws_secret_access_key|secret_key)\s*[:=]\s*['"]([a-zA-Z0-9/+=]{40})['"]""",
     "critical", "CWE-798",
     "AWS secret access key detected",
     "Use IAM roles or AWS_SECRET_ACCESS_KEY env var"),
    ("private_key",
     r"""-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----""",
     "critical", "CWE-321",
     "Private key embedded in source code",
     "Store keys in a secure vault, never commit to source control"),
    ("bearer_token",
     r"""(?:bearer|token|auth)\s*[:=]\s*['"]([a-zA-Z0-9_\-.]{20,})['"]""",
     "medium", "CWE-798",
     "Possible hardcoded bearer/auth token",
     "Use environment variables for authentication tokens"),
    ("password_assignment",
     r"""(?:password|passwd|pwd|secret)\s*[:=]\s*['"](?!(?:None|null|''|""|<|{|\*|test|example|placeholder|changeme)\b)[^'"]{8,}['"]""",
     "high", "CWE-798",
     "Possible hardcoded password or secret",
     "Use environment variables or a secrets manager"),
    ("jwt_token",
     r"""eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}""",
     "high", "CWE-798",
     "JWT token detected in source code",
     "Never hardcode JWT tokens; generate at runtime"),
    ("slack_webhook",
     r"""https://hooks\.slack\.com/services/T[a-zA-Z0-9_]+/B[a-zA-Z0-9_]+/[a-zA-Z0-9_]+""",
     "high", "CWE-798",
     "Slack webhook URL detected",
     "Store webhook URL in environment variable"),
    ("connection_string",
     r"""(?:mysql|postgres|postgresql|mongodb|redis)://[^'"\s]{10,}""",
     "high", "CWE-798",
     "Database connection string with possible credentials",
     "Use DATABASE_URL environment variable"),
]

SECRET_PATTERNS: list[SecurityPattern] = [
    SecurityPattern(
        name=name,
        pattern=re.compile(regex, re.IGNORECASE if name not in (
            "openai_key", "anthropic_key", "github_token", "github_oauth",
            "aws_access_key", "private_key", "jwt_token", "slack_webhook",
        ) else 0),
        severity=Severity(sev),
        category=Category.SECRET,
        cwe_id=cwe,
        message=msg,
        recommendation=rec,
    )
    for name, regex, sev, cwe, msg, rec in _SECRET_DEFS
]

# ---------------------------------------------------------------------------
# Code anti-pattern detection (DETECTORS only — these find risky code)
# ---------------------------------------------------------------------------

# These regex patterns DETECT dangerous constructs in scanned source files.
# They do NOT themselves call or use any dangerous functions.
_ANTI_PATTERN_DEFS: list[tuple[str, str, str, str, str, str, list[str], bool]] = [
    # (name, regex, severity, cwe, message, recommendation, languages, scan_comments)
    # Python detectors
    ("python_dynamic_eval",
     r"""\beval\s*\(""",
     "high", "CWE-95",
     "Dynamic code evaluation detected — code injection risk",
     "Use ast.literal_eval() for data, or avoid dynamic evaluation",
     ["python"], False),
    ("python_dynamic_exec",
     r"""\bexec\s*\(""",
     "high", "CWE-95",
     "Dynamic code execution detected — code injection risk",
     "Avoid dynamic code execution; use structured alternatives",
     ["python"], False),
    ("python_shell_true",
     r"""subprocess\.\w+\([^)]*shell\s*=\s*True""",
     "high", "CWE-78",
     "subprocess with shell=True — command injection risk",
     "Use subprocess with shell=False and pass args as list",
     ["python"], False),
    ("python_shell_true_standalone",
     r"""shell\s*=\s*True""",
     "medium", "CWE-78",
     "shell=True detected — possible command injection risk (check if used with subprocess)",
     "Use subprocess with shell=False and pass args as list",
     ["python"], False),
    ("python_pickle_loads",
     r"""pickle\.loads?\s*\(""",
     "high", "CWE-502",
     "pickle.load/loads — deserialization of untrusted data risk",
     "Use json or other safe serialization formats",
     ["python"], False),
    ("python_yaml_unsafe",
     r"""yaml\.load\s*\([^,)]+\)""",
     "medium", "CWE-502",
     "yaml.load() without SafeLoader — arbitrary code execution risk",
     "Use yaml.safe_load() or yaml.load(data, Loader=SafeLoader)",
     ["python"], False),
    ("python_sql_fstring",
     r"""(?:cursor\.execute|\.execute)\s*\(\s*f['"]""",
     "high", "CWE-89",
     "f-string in SQL query — SQL injection risk",
     "Use parameterized queries with ? or %s placeholders",
     ["python"], False),
    ("python_verify_false",
     r"""verify\s*=\s*False""",
     "medium", "CWE-295",
     "SSL verification disabled (verify=False)",
     "Enable SSL verification; use a CA bundle if needed",
     ["python"], False),
    ("python_weak_hash",
     r"""hashlib\.(?:md5|sha1)\s*\(""",
     "low", "CWE-328",
     "Weak hash algorithm (MD5/SHA1) — not suitable for security",
     "Use hashlib.sha256() or hashlib.sha3_256() for security",
     ["python"], False),
    ("python_tempfile_insecure",
     r"""tempfile\.mktemp\s*\(""",
     "medium", "CWE-377",
     "tempfile.mktemp() — race condition vulnerability",
     "Use tempfile.mkstemp() or tempfile.NamedTemporaryFile()",
     ["python"], False),
    # JavaScript/TypeScript detectors
    ("js_dynamic_eval",
     r"""\beval\s*\(""",
     "high", "CWE-95",
     "Dynamic code evaluation detected — code injection risk",
     "Avoid dynamic evaluation; use JSON.parse() for data",
     ["javascript", "typescript"], False),
    ("js_innerhtml",
     r"""\.innerHTML\s*=""",
     "medium", "CWE-79",
     "Direct innerHTML assignment — XSS risk",
     "Use textContent or a DOM sanitizer library",
     ["javascript", "typescript"], False),
    ("js_dangerously_set",
     r"""dangerouslySetInnerHTML""",
     "medium", "CWE-79",
     "dangerouslySetInnerHTML — XSS risk in React",
     "Sanitize content with DOMPurify before rendering",
     ["javascript", "typescript"], False),
    ("js_document_write",
     r"""document\.write\s*\(""",
     "medium", "CWE-79",
     "document.write() — XSS risk and bad practice",
     "Use DOM manipulation methods instead",
     ["javascript", "typescript"], False),
    # GlassWorm-class supply-chain detectors
    ("invisible_unicode_run",
     r"""[\u200B-\u200F\u2060-\u206F\uFE00-\uFE0F]{3,}|(?:[\U000E0000-\U000E007F]|[\U000E0100-\U000E01EF]){3,}""",
     "high", "CWE-506",
     "Run of invisible/non-rendering Unicode characters — possible steganographic payload (supply-chain attack)",
     "Audit with 'hexdump -C' or 'cat -v'; legitimate source should not contain runs of zero-width/variation-selector/tag characters",
     [], True),
    ("js_eval_on_decoded",
     r"""\b(?:eval|Function)\s*\(\s*(?:new\s+Function\s*\(\s*)?[^)]*?\b(?:atob|decodeURIComponent|unescape)\s*\(""",
     "critical", "CWE-94",
     "eval/Function() called on decoded data (atob/decodeURIComponent/unescape) — supply-chain obfuscation pattern",
     "Never eval decoded strings; use JSON.parse() for data, or refactor to explicit logic",
     ["javascript", "typescript"], False),
    ("js_eval_on_buffer",
     r"""\b(?:eval|Function)\s*\(\s*(?:new\s+Function\s*\(\s*)?[^)]*?Buffer\.from\s*\([^)]*?(?:['"]base64['"]|['"]hex['"])""",
     "critical", "CWE-94",
     "eval/Function() called on Buffer.from(..., 'base64'|'hex') decoded data — supply-chain obfuscation pattern",
     "Never eval decoded Buffers; refactor to explicit logic",
     ["javascript", "typescript"], False),
    ("js_eval_on_fromcharcode",
     r"""\b(?:eval|Function)\s*\(\s*(?:new\s+Function\s*\(\s*)?[^)]*?String\.fromCharCode\s*\(""",
     "critical", "CWE-94",
     "eval/Function() called on String.fromCharCode(...) — classic obfuscation pattern",
     "Never eval char-code sequences; this is almost always malicious",
     ["javascript", "typescript"], False),
    ("python_eval_on_b64decode",
     r"""\b(?:eval|exec)\s*\(\s*[^)]*?\b(?:b64decode|base64\.b64decode|urlsafe_b64decode)\s*\(""",
     "critical", "CWE-94",
     "eval/exec called on base64.b64decode(...) — supply-chain obfuscation pattern",
     "Never eval decoded data; refactor to explicit logic",
     ["python"], False),
    ("python_exec_on_codecs_decode",
     r"""\b(?:eval|exec)\s*\(\s*[^)]*?(?:\bcodecs\.decode\s*\(|\bbytes\.fromhex\s*\(|\bzlib\.decompress\s*\()""",
     "critical", "CWE-94",
     "eval/exec called on codecs.decode/bytes.fromhex/zlib.decompress — obfuscation pattern",
     "Never eval decoded/decompressed data; refactor to explicit logic",
     ["python"], False),
    ("python_exec_on_marshal_loads",
     r"""\b(?:eval|exec)\s*\(\s*[^)]*?\bmarshal\.loads\s*\(""",
     "critical", "CWE-94",
     "eval/exec called on marshal.loads(...) — code injection via deserialization",
     "Never execute marshal-deserialized data from untrusted sources",
     ["python"], False),
    # Shai-Hulud / dynamic-require obfuscation: require() with string concatenation
    # or template interpolation — used to evade literal 'child_process' string detection.
    ("js_dynamic_require_concat",
     r"""require\s*\(\s*(?:["'][^"']*["']\s*\+|`[^`]*\$\{)""",
     "critical", "CWE-94",
     "require() called with concatenated string or template interpolation — supply-chain obfuscation (Shai-Hulud style)",
     "Use static string literals for require(); dynamic module loading is almost always an obfuscation indicator",
     ["javascript", "typescript"], False),
    # MDN explicitly warns that string-argument setTimeout/setInterval behaves like eval().
    # Legitimate callers pass functions; string arguments are near-universally obfuscation.
    ("js_settimer_string_arg",
     r"""\b(?:setTimeout|setInterval)\s*\(\s*["'`]""",
     "high", "CWE-95",
     "setTimeout/setInterval called with a string argument — behaves like eval()",
     "Pass a function reference instead of a string; string args are implicit dynamic code execution",
     ["javascript", "typescript"], False),
]

ANTI_PATTERNS: list[SecurityPattern] = [
    SecurityPattern(
        name=name,
        pattern=re.compile(regex),
        severity=Severity(sev),
        category=Category.ANTI_PATTERN,
        cwe_id=cwe,
        message=msg,
        recommendation=rec,
        languages=langs,
        scan_comments=scan_comments,
    )
    for name, regex, sev, cwe, msg, rec, langs, scan_comments in _ANTI_PATTERN_DEFS
]
