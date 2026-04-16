"""Rule-harness developer tooling.

This package holds dev-only utilities for the rule-bench harness:

- ``import_pack``: import community rule packs (semgrep-rules, bandit, gosec)
  with proper license attribution.
- ``scripts/seed_attocode_fixtures``: scaffold hand-labeled corpus stubs
  from existing example pack ``examples`` fields.

These are NOT shipped runtime code — they live under ``eval/`` because
they're invoked by humans (or CI) during pack maintenance, not by the
attocode runtime.
"""
