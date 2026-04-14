// Safe correctness patterns — true negatives
// no-expect: These should NOT trigger correctness rules

fn safe_to_owned(items: &[&str]) -> Vec<String> {
    items.iter().map(|s| s.to_string()).collect()
}

fn safe_clone_outside_loop(item: &String) -> String {
    item.clone()
}
