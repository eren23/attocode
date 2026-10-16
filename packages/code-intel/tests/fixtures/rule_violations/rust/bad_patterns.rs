// Rust file with intentional rule violations for testing.
//
// Each violation is annotated with // expect: <rule-id> on the same line.

use std::fs;

pub fn load_config(path: &str) -> String {
    // Team preference: library code should return Result, not expect
    let content = fs::read_to_string(path).expect("failed to read config"); // expect: rs-no-expect-in-lib
    content
}

pub fn process(data: &[u8]) -> Vec<u8> {
    // Builtin: clone in potential hot path
    let copy = data.to_vec().clone(); // expect: rs-clone-in-loop
    copy
}

pub fn clean_function(x: i32) -> i32 {
    // This function should produce NO findings
    x * 2
}
