// Auto-seeded fixture for rule 'go-defer-statement'.
// Hand-curate before relying on this for scoring:
//   - confirm `# expect:` lines target the actual offending line
//   - add nearby unrelated code so we measure FP rate
//   - ensure the file compiles in your target toolchain

// --- BAD: rule MUST fire ---
for _, f := range files {  // expect: go-defer-statement
    fd, _ := os.Open(f)
    defer fd.Close()
}

// --- GOOD: rule must NOT fire ---
for _, f := range files {  // ok: go-defer-statement
    func() {
        fd, _ := os.Open(f)
        defer fd.Close()
    }()
}
