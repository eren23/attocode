// Auto-seeded fixture for rule 'ts-array-push-spread'.
// Hand-curate before relying on this for scoring:
//   - confirm `# expect:` lines target the actual offending line
//   - add nearby unrelated code so we measure FP rate
//   - ensure the file compiles in your target toolchain

// --- BAD: rule MUST fire ---
result.push(...bigArray)  // expect: ts-array-push-spread

// --- GOOD: rule must NOT fire ---
for (const item of bigArray) result.push(item)  // ok: ts-array-push-spread
