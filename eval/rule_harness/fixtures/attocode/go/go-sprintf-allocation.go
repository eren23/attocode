// Auto-seeded fixture for rule 'go-sprintf-allocation'.
// Hand-curate before relying on this for scoring:
//   - confirm `# expect:` lines target the actual offending line
//   - add nearby unrelated code so we measure FP rate
//   - ensure the file compiles in your target toolchain

// --- BAD: rule MUST fire ---
key := fmt.Sprintf("cache:%s:%d", prefix, id)  // expect: go-sprintf-allocation

// --- GOOD: rule must NOT fire ---
key := "cache:" + prefix + ":" + strconv.Itoa(id)  // ok: go-sprintf-allocation
