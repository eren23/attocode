// Code injection — true positives for RULE ACCURACY TESTING
// nosec — INTENTIONALLY insecure corpus, NOT production code

function badEval(userInput) {  // nosec
    return eval(userInput);  // expect: security/js_dynamic_eval
}

function badFunction(code) {  // nosec
    return new Function(code)();  // expect: security/js_eval_on_buffer
}

function badSetTimeout(code) {  // nosec
    setTimeout("alert(1)", 1000);  // expect: security/js_settimer_string_arg
}
