// XSS patterns — true positives for RULE ACCURACY TESTING
// nosec — INTENTIONALLY insecure corpus, not production code

function badInnerHTML(userInput) {
    document.getElementById("output").innerHTML = userInput;  // expect: security/js_innerhtml
}

function badDocumentWrite(data) {
    document.write(data);  // expect: security/js_document_write
}

// nosec — intentional XSS test case for rule accuracy
function badDangerouslySet(props) {
    return { dangerouslySetInnerHTML: { __html: props.content } };  // expect: security/js_dangerously_set
}
