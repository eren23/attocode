// Safe Rust patterns — true negatives
// no-expect: These should NOT trigger unsafe/unwrap rules

fn safe_result_handling(input: &str) -> Result<i32, std::num::ParseIntError> {
    input.parse::<i32>()
}

fn safe_option(val: Option<i32>) -> i32 {
    val.unwrap_or(0)
}

fn safe_if_let(val: Option<String>) {
    if let Some(s) = val {
        println!("{}", s);
    }
}
