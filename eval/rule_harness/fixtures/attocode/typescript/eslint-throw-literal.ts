// Hand-curated fixture for eslint no-throw-literal.

class ValidationError extends Error {}

function validateGood(input: string): void {
  if (!input) {
    throw new Error("input required");           // ok: no-throw-literal
  }
  if (input.length > 100) {
    throw new ValidationError("too long");       // ok: no-throw-literal
  }
}

function validateBad(input: string): void {
  if (!input) {
    throw "input required";                       // expect: no-throw-literal
  }
  if (input.length > 100) {
    throw { code: "TOO_LONG", input };            // expect: no-throw-literal
  }
}
