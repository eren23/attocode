// Auto-seeded fixture for rule 'go-error-string-compare'.
// Hand-curate before relying on this for scoring:
//   - confirm `# expect:` lines target the actual offending line
//   - add nearby unrelated code so we measure FP rate
//   - ensure the file compiles in your target toolchain

// --- BAD: rule MUST fire ---
if err.Error() == "not found" {  // expect: go-error-string-compare

// --- GOOD: rule must NOT fire ---
if errors.Is(err, ErrNotFound) {  // ok: go-error-string-compare
