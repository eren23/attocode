// Auto-seeded fixture for rule 'ts-no-optional-chain'.
// Hand-curate before relying on this for scoring:
//   - confirm `# expect:` lines target the actual offending line
//   - add nearby unrelated code so we measure FP rate
//   - ensure the file compiles in your target toolchain

// --- BAD: rule MUST fire ---
if (user && user.address && user.address.city)  // expect: ts-no-optional-chain

// --- GOOD: rule must NOT fire ---
if (user?.address?.city)  // ok: ts-no-optional-chain
