# Auto-seeded fixture for rule 'py-bare-except'.
# Hand-curate before relying on this for scoring:
#   - confirm `# expect:` lines target the actual offending line
#   - add nearby unrelated code so we measure FP rate
#   - ensure the file compiles in your target toolchain

# --- BAD: rule MUST fire ---
try:  # expect: py-bare-except
    risky()
except:
    pass

# --- GOOD: rule must NOT fire ---
try:  # ok: py-bare-except
    risky()
except Exception as e:
    logger.error(e)
