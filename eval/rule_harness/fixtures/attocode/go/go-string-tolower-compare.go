// Auto-seeded fixture for rule 'go-string-tolower-compare'.
// Hand-curate before relying on this for scoring:
//   - confirm `# expect:` lines target the actual offending line
//   - add nearby unrelated code so we measure FP rate
//   - ensure the file compiles in your target toolchain

// --- BAD: rule MUST fire ---
if strings.ToLower(name) == "admin" {  // expect: go-string-tolower-compare

// --- GOOD: rule must NOT fire ---
if strings.EqualFold(name, "admin") {  // ok: go-string-tolower-compare
