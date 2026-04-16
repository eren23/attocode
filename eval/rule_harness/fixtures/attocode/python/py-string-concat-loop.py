# Auto-seeded fixture for rule 'py-string-concat-loop'.
# Hand-curate before relying on this for scoring:
#   - confirm `# expect:` lines target the actual offending line
#   - add nearby unrelated code so we measure FP rate
#   - ensure the file compiles in your target toolchain

# --- BAD: rule MUST fire ---
result = ''  # expect: py-string-concat-loop
for item in items:
    result += str(item)

# --- GOOD: rule must NOT fire ---
result = ''.join(str(item) for item in items)  # ok: py-string-concat-loop
