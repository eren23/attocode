# Auto-seeded fixture for rule 'py-dict-keys-iteration'.
# Hand-curate before relying on this for scoring:
#   - confirm `# expect:` lines target the actual offending line
#   - add nearby unrelated code so we measure FP rate
#   - ensure the file compiles in your target toolchain

# --- BAD: rule MUST fire ---
for key in config.keys():  # expect: py-dict-keys-iteration

# --- GOOD: rule must NOT fire ---
for key in config:  # ok: py-dict-keys-iteration
