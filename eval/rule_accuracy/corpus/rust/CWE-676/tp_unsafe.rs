// Unsafe and unwrap patterns — true positives
// INTENTIONALLY insecure for rule accuracy testing

fn bad_unsafe_deref(ptr: *const i32) -> i32 {
    unsafe {  // expect: rust/rs-unsafe-block
        *ptr
    }
}

fn bad_unwrap(input: &str) -> i32 {
    input.parse::<i32>().unwrap()  // expect: rust/rs-unwrap-usage
}

fn bad_unsafe_transmute() {
    unsafe {  // expect: rust/rs-unsafe-block
        std::mem::transmute::<u32, f32>(42);
    }
}
