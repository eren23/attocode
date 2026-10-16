// Java file with intentional rule violations for testing.
//
// Each violation is annotated with // expect: <rule-id> on the same line.
package com.example;

import java.util.List;

public class BadPatterns {

    public String buildMessage(List<String> items) {
        // Builtin: string concat in loop
        String result = "";
        for (String item : items) {
            result += "item: " + item; // expect: java-string-concat-loop
        }
        System.out.println("Done: " + result); // expect: java-no-system-out
        return result;
    }

    public void riskyMethod() {
        try {
            loadData();
        } catch (Exception e) { // expect: java-catch-exception
            System.out.println(e.getMessage()); // expect: java-no-system-out
        }
    }

    private void cleanLoadData() throws Exception {
        // clean — no findings expected
        throw new Exception("not implemented");
    }
}
