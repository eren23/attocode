// Code injection — true positives for RULE ACCURACY TESTING
// nosec — INTENTIONALLY insecure corpus

function badEvalTs(code: string) {  // nosec
    return eval(code);  // expect: security/js_dynamic_eval
}
