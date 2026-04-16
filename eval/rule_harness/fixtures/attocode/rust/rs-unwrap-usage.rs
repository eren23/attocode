// Auto-seeded fixture for rule 'rs-unwrap-usage'.
// Hand-curate before relying on this for scoring:
//   - confirm `# expect:` lines target the actual offending line
//   - add nearby unrelated code so we measure FP rate
//   - ensure the file compiles in your target toolchain

// --- BAD: rule MUST fire ---
let value = result.unwrap();  // expect: rs-unwrap-usage

// --- GOOD: rule must NOT fire ---
let value = result.expect("config must be valid");  // ok: rs-unwrap-usage
