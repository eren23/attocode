// Hand-curated fixture for eslint eqeqeq + no-var.

const STRICT_MODE = true;

function badEquality(a: unknown, b: unknown): boolean {
  if (a == b) {                  // expect: eqeqeq
    return true;
  }
  if (a != null) {               // expect: eqeqeq
    return false;
  }
  return false;
}

function goodEquality(a: unknown, b: unknown): boolean {
  if (a === b) {                 // ok: eqeqeq
    return true;
  }
  return a !== null;             // ok: eqeqeq
}

// --- BAD: var keyword ---
var legacyName = "old style";    // expect: no-var

// --- GOOD: const / let ---
const goodName = "modern";       // ok: no-var
let mutableName = "modern";      // ok: no-var
