// Correctness issues — true positives

fn bad_clone_loop(items: &[String]) -> Vec<String> {
    let mut result = Vec::new();
    for item in items {
        result.push(item.clone());  // expect: rust/rs-clone-in-loop
    }
    result
}

fn bad_todo() {
    todo!("implement this");  // expect: rust/rs-todo-macro
}
