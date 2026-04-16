// Auto-seeded fixture for rule 'go-append-no-prealloc'.
// Hand-curate before relying on this for scoring:
//   - confirm `# expect:` lines target the actual offending line
//   - add nearby unrelated code so we measure FP rate
//   - ensure the file compiles in your target toolchain

// --- BAD: rule MUST fire ---
var results []string  // expect: go-append-no-prealloc
for _, item := range items {
    results = append(results, item.Name)
}

// --- GOOD: rule must NOT fire ---
results := make([]string, 0, len(items))  // ok: go-append-no-prealloc
for _, item := range items {
    results = append(results, item.Name)
}
