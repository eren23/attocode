# Rule-Bench Corpus

The rule-bench harness measures rule precision/recall against a labeled corpus, then drives LLM-guided optimization to tune rule fields and generate new rules. This guide covers:

- The labeled corpus contract (what a fixture looks like)
- How to add a new community pack with proper license attribution
- The hand-labeling workflow for attocode-specific fixtures
- Running `--bench rule` and reading the results
- Quarterly upstream-license maintenance

For the broader optimization framework see [Meta-Harness Optimization](meta-harness-optimization.md).

## Why a labeled corpus

A rule's value is "true positives caught minus false positives raised, weighted by severity". You can only measure that against fixtures someone wrote down the answer for. Without labels, the optimizer is flying blind.

## Annotation format

Fixtures use inline comments to mark expectations:

| Marker | Meaning |
|---|---|
| `# expect: rule-id` | Rule MUST fire on this line (TP assertion) |
| `# ok: rule-id` | Rule must NOT fire on this line (FP guard) |
| `# todoruleid: rule-id` | Known miss — informational, not scored |
| `# ruleid: rule-id` | Semgrep alias — automatically normalized to `expect` |

`//` works in place of `#` for languages with C-style comments. The annotation regex lives at `attocode.code_intel.rules.testing._ANNOTATION_RE`.

Example (`eval/rule_harness/fixtures/attocode/python/bandit-secrets.py`):

```python
api_key = "sk-1234567890abcdef"  # expect: B105-hardcoded-password
PLACEHOLDER = "EXAMPLE_VALUE"    # ok: B105-hardcoded-password
```

## Corpus sources (in priority order)

The `CorpusLoader` discovers fixtures from three sources, in this order:

1. **Community pack fixtures** — `packs/community/<pack>/fixtures/<rule-id>/{positive,negative}.<ext>`. Honors `--packs` filter.
2. **Hand-labeled attocode fixtures** — `eval/rule_harness/fixtures/attocode/<lang>/*.<ext>`. Targets the shipped example packs.
3. **Legacy CWE corpus** — `eval/rule_accuracy/corpus/<lang>/<cwe>/{tp_,tn_}<name>.<ext>`. Pre-existing benchmark, kept for back-compat.

Toggle each source via CLI flags:

```bash
python -m eval.meta_harness --bench rule \
    --include-community --include-attocode-fixtures --include-legacy-corpus \
    baseline
```

When `--packs` is unset, all three sources are enabled by default.

## Adding a community pack

Community packs live under `src/attocode/code_intel/rules/packs/community/<pack-name>/` with their own `LICENSE` + `NOTICE` files plus a `manifest.yaml` declaring source provenance.

### License policy

**Permissive licenses only.** The CI job `pack-license-check` (`scripts/check_pack_licenses.py`) enforces this on every push:

| Source license | Allowed | Required attribution |
|---|---|---|
| MIT | yes | Copyright notice + license text |
| Apache-2.0 | yes | NOTICE file + license text |
| BSD-2/3-Clause | yes | Copyright notice + license text |
| ISC | yes | Copyright notice + license text |
| LGPL-2.1+ | **no** — copyleft adds redistribution friction | n/a |
| GPL | **no** — incompatible with attocode's distribution model | n/a |

Bundled license templates ship under `packs/community/_license_templates/`.

### Scaffold a new pack

Use the importer to scaffold a license-compliant skeleton:

```bash
uv run python -m eval.rule_harness.import_pack \
    --source bandit \
    --lang python \
    --output src/attocode/code_intel/rules/packs/community/bandit-python \
    --commit <upstream-sha>
```

Built-in sources (each contributes a `PORTING.md` checklist of high-value rule IDs):

- `bandit` (Apache-2.0) → Python security rules
- `gosec` (Apache-2.0) → Go security rules
- `eslint` (MIT) → JavaScript/TypeScript lint rules

The scaffolder produces:

```
packs/community/bandit-python/
├── LICENSE         # Apache-2.0 full text
├── NOTICE          # attribution + provenance
├── manifest.yaml   # name, source, source_url, source_commit, source_license, …
├── PORTING.md      # checklist of upstream rule IDs to hand-port
└── rules/          # empty — fill with attocode YAML rules
```

### Hand-port a rule

For each rule in `PORTING.md`, write a YAML file under `rules/` with the attribution comment header at the top:

```yaml
# Adapted from bandit rule 'B105 hardcoded_password_string'
# See ../LICENSE and ../NOTICE for license terms.

id: B105-hardcoded-password
name: Hardcoded password string
message: Possible hardcoded password assignment
severity: high
category: security
languages: [python]
confidence: 0.7
cwe: CWE-798
pattern: '(?i)\b(password|passwd|pwd|secret|token|api_key)\s*=\s*[''"][^''"]{3,}[''"]'
explanation: |
  Storing credentials in source code makes them easy to leak …
recommendation: |
  Move credentials to a secret manager …
references:
  - https://bandit.readthedocs.io/en/latest/plugins/b105_hardcoded_password_string.html
  - https://cwe.mitre.org/data/definitions/798.html
```

Pattern guidance:

- Prefer narrow patterns over broad ones — false positives kill adoption.
- Use `(?i)` for case-insensitive matches when the language permits.
- Test with `python -m eval.meta_harness --bench rule baseline` and inspect the per-rule F1 in `rule_baseline.json`.

### Adding fixtures

Drop labeled samples under `packs/community/<pack>/fixtures/<rule-id>/`:

```
fixtures/B105-hardcoded-password/
├── positive.py    # rule MUST fire here (annotated with `# expect:`)
└── negative.py    # rule must NOT fire (annotated with `# ok:`)
```

Each file should compile in its language toolchain so optional LSP enrichment doesn't choke. Include unrelated nearby code in `negative.py` to measure FP rate against realistic non-targets.

## Hand-labeling attocode fixtures

For the shipped example packs (`packs/examples/<lang>/`), fixtures live at `eval/rule_harness/fixtures/attocode/<lang>/<rule-id>.<ext>`. Use the seed scaffolder to generate stubs from each rule's `examples` field:

```bash
uv run python -m eval.rule_harness.scripts.seed_attocode_fixtures
```

Output:

```
Seeded 15 fixture stub(s)
  go: 6
  java: 1
  python: 4
  rust: 1
  typescript: 3
```

Then **hand-curate each fixture**:

1. Confirm the `# expect:` line targets the actual offending position
2. Add nearby unrelated code so we measure FP rate
3. Ensure the file compiles in your target toolchain
4. Add at least one `# ok:` annotation per rule for FP guarding

Pass `--overwrite` to regenerate fixtures (destroys hand-curation).

## Running the harness

### Baseline

```bash
# Score the current corpus with default rule overrides
python -m eval.meta_harness --bench rule baseline
```

Output (truncated):

```
Composite score: 0.8854

Component scores:
  weighted_f1: 0.8444
  precision: 0.9135
  recall: 0.7851

Rule-bench per language:
  go: F1=0.7191
  java: F1=0.8235
  python: F1=0.9714
  rust: F1=0.9474
  typescript: F1=0.9655
```

The full per-rule + per-language report lands in `.attocode/meta_harness/results/rule_baseline.json`.

### Optimization

```bash
# Sweep mode (no API key required)
python -m eval.meta_harness --bench rule run --iterations 10 --propose-mode sweep

# LLM mode (needs OPENROUTER_API_KEY or ANTHROPIC_API_KEY)
python -m eval.meta_harness --bench rule run --iterations 10 --propose-mode llm
```

The runner appends every candidate to `rule_evolution_summary.jsonl` with full per-language F1 and the `reject_reason` for floor violations. The best accepted config lands in `rule_best_config.yaml`.

### Per-language floor

A candidate is accepted only when:

1. Its composite score strictly improves on the current best, AND
2. **No language drops below 95% of its baseline F1** (the floor predicate, in `rule_bench/predicate.py`).

This prevents the "win-Python-break-Go" pattern observed in the original search-bench experiments. Configurable via `make_rule_accept_predicate(floor_ratio=…)` if 5% slack is too strict for your corpus.

### Composite mode

Run search + rule together:

```bash
python -m eval.meta_harness --bench composite baseline
```

Composite formula: `0.3 * search_quality + 0.5 * mcp_bench + 0.2 * rule_bench`. The rule-leg per-language scores still drive the floor predicate.

## Stage-2 template proposer

When `--propose-mode llm` runs, the proposer can also instantiate rule templates from `eval/meta_harness/rule_bench/templates/`:

- `deprecated_api_call`
- `missing_error_check`
- `insecure_default_arg`
- `regex_redos`
- `string_concat_in_loop`
- `unsafe_deserialization`

Each template declares slots (regex_fragment, language, enum, text). The LLM fills slots; the engine validates each (regex compiles, language supported, enum value valid) and runs a fixture-coverage gate (must earn ≥2 TPs, ≤1 FP across the labeled corpus) before the rule reaches the full evaluator.

To add a template, drop a YAML file in `templates/` matching the schema in `template_engine.py:Template`.

## Quarterly maintenance

Upstream rule sources occasionally relicense or restructure. Recommended cadence:

1. **Every quarter**, refresh each community pack:
   - Re-clone the upstream repo at the latest commit
   - Re-run `import_pack.py --commit <new-sha>` (regenerates manifest)
   - Diff the upstream rule list against `PORTING.md`; port newly-relevant rules
2. **Whenever upstream changes license**, audit the change (`License: …` line in NOTICE) and either keep the pinned commit or remove the pack
3. **Run `scripts/check_pack_licenses.py` locally** before opening any pack-related PR

## Troubleshooting

**Rule baseline is 0.0** — the registry is empty. Pass `--packs <name>` or run with no `--packs` to load all shipped + community packs.

**A specific language has F1 = 0** — either no rules target that language OR no fixtures exist for it. Check `rule_baseline.json` → `per_language` for `rule_count` and `fixture_count`.

**Floor predicate rejects every candidate** — your baseline-per-lang vector includes a language with very high F1 (close to 1.0). Even small noise breaches the 5% floor. Either widen the floor (`make_rule_accept_predicate(floor_ratio=0.9)`) or add more fixtures to stabilize the per-language signal.

**LLM proposer returns 0 candidates** — most often the fixture-coverage gate is rejecting them. Check your corpus has at least 2 examples per rule the LLM is targeting; otherwise no template instance can earn 2 TPs.
