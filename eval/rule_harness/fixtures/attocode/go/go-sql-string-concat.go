// Auto-seeded fixture for rule 'go-sql-string-concat'.
// Hand-curate before relying on this for scoring:
//   - confirm `# expect:` lines target the actual offending line
//   - add nearby unrelated code so we measure FP rate
//   - ensure the file compiles in your target toolchain

// --- BAD: rule MUST fire ---
db.Query("SELECT * FROM users WHERE id=" + id)  // expect: go-sql-string-concat

// --- GOOD: rule must NOT fire ---
db.Query("SELECT * FROM users WHERE id=?", id)  // ok: go-sql-string-concat
