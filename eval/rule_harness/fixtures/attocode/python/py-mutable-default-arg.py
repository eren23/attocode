# Auto-seeded fixture for rule 'py-mutable-default-arg'.
# Hand-curate before relying on this for scoring:
#   - confirm `# expect:` lines target the actual offending line
#   - add nearby unrelated code so we measure FP rate
#   - ensure the file compiles in your target toolchain

# --- BAD: rule MUST fire ---
def add(item, items=[]):  # expect: py-mutable-default-arg
    items.append(item)
    return items

# --- GOOD: rule must NOT fire ---
def add(item, items=None):  # ok: py-mutable-default-arg
    if items is None:
        items = []
    items.append(item)
    return items
