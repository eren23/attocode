// Auto-seeded fixture for rule 'java-string-concat-loop'.
// Hand-curate before relying on this for scoring:
//   - confirm `# expect:` lines target the actual offending line
//   - add nearby unrelated code so we measure FP rate
//   - ensure the file compiles in your target toolchain

// --- BAD: rule MUST fire ---
String result = "";\nfor (String s : items) result += s;  // expect: java-string-concat-loop

// --- GOOD: rule must NOT fire ---
StringBuilder sb = new StringBuilder();  // ok: java-string-concat-loop
for (String s : items) sb.append(s);
