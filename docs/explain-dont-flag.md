# Explain, Don't Just Flag

## The Problem with Traditional SAST

Traditional static analysis tools output this:

```
src/db.py:42: CWE-89 SQL injection [high]
```

A file, a line number, a CWE code, a severity. The developer must:
1. Navigate to the file
2. Understand the CWE
3. Determine if it's a real issue or a false positive
4. Figure out how to fix it
5. Verify the fix doesn't break anything

This workflow has a 92% false positive rate in real-world SAST deployments (SastBench, 2025). Developers learn to ignore findings. Alert fatigue kills security.

## The attocode Approach

attocode rules produce a **teaching package**, not just a flag:

```markdown
## [high] SQL injection via string formatting

**File**: src/db.py:42
**CWE**: CWE-89
**Confidence**: 0.85

### Code
```python
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
```

### Why This Matters
F-strings in SQL queries allow malicious input to alter query structure.
An attacker controlling `user_id` can inject `'; DROP TABLE users; --`
to execute arbitrary SQL commands.

### How to Fix
Use parameterized queries — the database driver handles escaping.

### Examples
❌ `cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")`
✅ `cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))`

Parameterization prevents injection because the query structure and
data are sent separately to the database engine.
```

The AI coding agent receives this and can **immediately act**: apply the fix, explain it to the developer, or triage based on confidence.

## Three Pillars

### 1. Agent-Native Rules

Every attocode rule includes fields that traditional SAST tools don't have:

| Field | Purpose | Who Benefits |
|-------|---------|-------------|
| `explanation` | Why this matters | AI agent understands context |
| `recommendation` | How to fix | AI agent can act immediately |
| `examples` | Bad → good code pairs | AI agent learns the pattern |
| `confidence` | How likely this is real | AI agent triages autonomously |
| `captures` | Metavar bindings | AI agent generates precise fixes |

No competitor has this structure. Semgrep rules have `message` and `fix`. CodeQL has `message`. ESLint has `message`. None provide the teaching context that enables autonomous agent action.

### 2. MCP-Native Delivery

attocode rules are delivered through MCP (Model Context Protocol) tools. The AI agent can:

- **Query rules**: `list_rules(language="python", category="security")`
- **Run analysis**: `analyze(path="src/", severity="high")`
- **Register rules at runtime**: `register_rule(yaml_content="...")`
- **Install community packs**: `install_community_pack("owasp-top10")`
- **Record feedback**: `rule_feedback(rule_id="...", is_true_positive=True)`

Rules are part of the agent's reasoning loop, not a separate pipeline that dumps a report. The agent discovers, applies, and learns from rules in real-time.

### 3. Dual-Mode Output

The same `UnifiedRule` model produces both:

- **Agent mode**: Rich markdown with context, explanation, examples, recommendations
- **CI mode**: SARIF v2.1.0 for GitHub Code Scanning, VS Code, Azure DevOps

Teams don't maintain two rule sets — one for their AI assistant and one for their CI pipeline. The `explanation` and `examples` fields render in both modes: in agent mode as rich context, in SARIF as `help.markdown` and custom property bags.

## Competitive Positioning

**vs. Semgrep**: "Semgrep tells your CI what's wrong. attocode teaches your AI agent why it matters and how to fix it — and runs in CI too."

**vs. Cursor rules / CLAUDE.md**: "Convention files give the AI instructions in English. attocode rules give precision: regex patterns, confidence scores, CWE references, and concrete code examples. And they enforce in CI."

**vs. CodeQL**: "CodeQL requires learning a dedicated query language. attocode rules are YAML — readable, editable, and enrichable by AI agents themselves."

**vs. ast-grep MCP**: "ast-grep gives structural search. attocode gives structural search + semantic search + dependency graphs + community detection + impact analysis + a rule engine with 17-language packs — all through one MCP server."

## The Benchmark Proves It

The code-intel-bench benchmark (120 tasks, 8 categories, 20 repos) shows:

- **4.7/5** average quality score vs grep (4.0) and ast-grep (2.8)
- **Rule accuracy**: F1 = 0.87 across 57 rules, 6 languages, 13 CWE categories
- **First code-intelligence MCP benchmark** — no existing benchmark covers this space

The combination of agent-native rules + MCP delivery + dual-mode output is unique. No competitor covers all three.
