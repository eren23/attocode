# attocode Rule Format Specification v1.0

The attocode rule format is a YAML-based schema for defining static analysis rules that are **agent-native** — designed to give AI coding agents everything they need to triage, fix, and explain issues.

## What Makes This Format Different

Traditional SAST tools output a rule ID and a line number. attocode rules output a **teaching package**: explanation, recommendation, few-shot examples, confidence scores, and CWE references. This is the competitive moat — no other rule format provides this level of agent-ready context.

| Feature | Semgrep | CodeQL | ESLint | **attocode** |
|---------|---------|--------|--------|-------------|
| Pattern format | AST + metavars | Datalog (QL) | JS visitors | Regex + metavars + composites |
| Rule file format | YAML | QL files | JavaScript | **YAML** |
| Explanation field | message only | message only | message only | **explanation + recommendation** |
| Few-shot examples | No | No | No | **Yes (bad -> good code)** |
| Confidence score | No | No | No | **Yes (0.0-1.0)** |
| Autofix | metavar-based | No | function-based | **metavar-based** |
| CI + Agent dual mode | CI only | CI only | CI only | **Both (SARIF + rich markdown)** |

## Schema

### Required Fields

```yaml
id: string          # Unique identifier (e.g., "py-mutable-default-arg")
pattern: string     # Regex pattern or metavar pattern ($VAR syntax)
message: string     # What was detected (shown in findings)
severity: string    # critical | high | medium | low | info
```

### Optional Fields

```yaml
# Classification
category: string       # correctness | suspicious | complexity | performance | style | security | deprecated
languages: [string]    # Language filter (empty = all languages)
cwe: string           # CWE identifier (e.g., "CWE-89")
tags: [string]        # Freeform tags for filtering
confidence: float     # 0.0-1.0, default 0.8

# Agent-native context (the differentiator)
explanation: string       # WHY this matters — not just what, but why
recommendation: string    # HOW to fix — concrete guidance
examples:                 # Few-shot examples for the AI agent
  - bad: string          # Code that triggers the rule
    good: string         # Corrected code
    explanation: string  # Why the good version is better

# Pattern composition (boolean combinators)
patterns:                 # Alternative to single 'pattern' — composite matching
  - pattern: string      # Primary pattern (must match)
  - pattern-not: string  # Line must NOT match this
  - pattern-inside: string    # Scope pattern must exist above (indentation-aware)
  - pattern-not-inside: string # Scope pattern must NOT exist above

# Alternative: multiple patterns (OR)
pattern-either:           # Any of these patterns triggers the rule
  - string
  - string

# Metavariable constraints (post-match filtering)
metavariable-regex:       # Captured $VAR must match regex
  $FUNC: "^(query|execute)$"
metavariable-comparison:  # Captured $NUM must satisfy comparison
  $NUM: "> 1000"

# Autofix
fix:
  search: string    # Pattern to find (supports $VAR references)
  replace: string   # Replacement (supports $VAR references)

# Self-test (validated at load time)
test_cases:
  - code: string
    should_match: true|false

# Behavior
scan_comments: bool     # Whether to scan comment lines (default: false)
enabled: bool          # Whether rule is active (default: true)
```

## Metavariable System

Pattern strings containing `$IDENTIFIER` tokens are compiled with named capture groups:

| Metavar | Matches | Regex |
|---------|---------|-------|
| `$FUNC`, `$NAME`, `$VAR` | Identifiers | `\w+` |
| `$ARG`, `$EXPR`, `$VALUE` | Expressions | `[^,)]+` |
| `$STR` | String literals | `["'][^"']*["']` |
| `$NUM` | Numbers | `\d+(?:\.\d+)?` |
| `$TYPE` | Type annotations | `[\w.\[\]]+` |
| `$...` | Any (non-capturing) | `.*?` |

Repeated metavars create back-references: `$VAR == $VAR` matches `x == x` but not `x == y`.

## Examples

### Simple rule
```yaml
- id: py-mutable-default-arg
  pattern: 'def\s+\w+\s*\([^)]*(?:=\s*\[\]|=\s*\{\})'
  message: "Mutable default argument — shared across all calls"
  severity: medium
  category: correctness
  languages: [python]
  confidence: 0.85
  explanation: >
    Default mutable arguments are evaluated once at function definition,
    not at each call. All calls sharing the default mutate the same object.
  recommendation: "Use None as default: if arg is None: arg = []"
  examples:
    - bad: "def add(item, items=[]):"
      good: "def add(item, items=None):"
      explanation: "None default + conditional creation avoids shared state"
```

### Metavar rule with constraints
```yaml
- id: sql-string-format
  pattern: '$FUNC($STR + $VAR)'
  message: "$FUNC called with string concatenation — SQL injection risk"
  severity: high
  category: security
  cwe: CWE-89
  metavariable-regex:
    $FUNC: "^(query|execute|run_sql)$"
  fix:
    search: '$FUNC($STR + $VAR)'
    replace: '$FUNC($STR, [$VAR])'
```

### Composite rule with scope
```yaml
- id: sprintf-in-loop
  patterns:
    - pattern: 'fmt\.Sprintf\s*\('
    - pattern-inside: 'for\s.*\{'
    - pattern-not: '// nolint'
  message: "fmt.Sprintf inside loop — consider pre-allocating"
  severity: medium
  category: performance
  languages: [go]
```

## Pack Structure

```
.attocode/packs/<name>/
  manifest.yaml       # name, version, languages, description
  rules/*.yaml        # Rule definitions
  taint/              # Optional taint analysis definitions
    sources.yaml
    sinks.yaml
    sanitizers.yaml
```

### Manifest
```yaml
name: python
version: 1.0.0
languages: [python]
description: "Python analysis pack"
```
