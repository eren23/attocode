// Auto-seeded fixture for rule 'ts-await-in-loop'.
// Hand-curate before relying on this for scoring:
//   - confirm `# expect:` lines target the actual offending line
//   - add nearby unrelated code so we measure FP rate
//   - ensure the file compiles in your target toolchain

// --- BAD: rule MUST fire ---
for (const id of ids) {  // expect: ts-await-in-loop
  const data = await fetch(id);
}

// --- GOOD: rule must NOT fire ---
const results = await Promise.all(ids.map(id => fetch(id)));  // ok: ts-await-in-loop
