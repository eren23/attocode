# Rule Analysis Demo

> Example output from the rule-based analysis engine. This report was generated
> by running `scripts/generate_rule_analysis_report.py` against intentionally
> flawed fixture files in 5 languages (Python, Go, TypeScript, Rust, Java).
>
> Each finding includes code context, explanations, fix suggestions, and
> bad-vs-good examples — everything the connected coding agent needs to
> triage and fix issues without additional tool calls.
>
> **To generate your own:** `python scripts/generate_rule_analysis_report.py --path /your/project`

## Summary

| Metric | Value |
|--------|-------|
| Rules loaded | 150 (5 packs) |
| Findings | **19** across 5 files |
| 🟠 High | 1 |
| 🟡 Medium | 12 |
| 🔵 Low | 5 |
| ⚪ Info | 1 |

## By Category

| 🎨 **style** | ███████ 7 |
| 🐛 **correctness** | ██████ 6 |
| ⚡ **performance** | ██████ 6 |

## Severity Distribution

```
  critical  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░    0 (0%)
      high  ██░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░    1 (5%)
    medium  █████████████████████████░░░░░░░░░░░░░░░   12 (63%)
       low  ██████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░    5 (26%)
      info  ██░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░    1 (5%)
```

## Findings by File

### `go/bad_patterns.go` `go`

#### 🟠 Line 18: go-no-panic

```go
    15 | func HandleRequest(name string) string {
    16 | 	// Team preference: no panic
    17 | 	if name == "" {
>  18 | 		panic("name cannot be empty") // expect: go-no-panic
    19 | 	}
    20 | 
    21 | 	// Builtin: string comparison without EqualFold
```

**HIGH** | 🐛 correctness | Confidence: 90%

**What:** Don't panic — return errors instead

!!! warning "Why this matters"
    In our services, panics crash the entire process. Go's error return convention exists specifically to avoid this. Only panic for truly unrecoverable programmer errors in init().


**Fix:** Return error instead: return fmt.Errorf(...)

=== "Bad"
    ```go
    panic("config not found")
    ```
=== "Good"
    ```go
    return fmt.Errorf("config not found: %w", err)
    ```

---

#### 🟡 Line 11: go-no-init-function

```go
     8 | 	"strings"
     9 | )
    10 | 
>  11 | func init() { // expect: go-no-init-function
    12 | 	fmt.Println("initializing")
    13 | }
    14 | 
```

**MEDIUM** | 🎨 style | Confidence: 85%

**What:** Avoid init() — use explicit initialization for testability

!!! warning "Why this matters"
    init() functions run implicitly at import time, making it impossible to control initialization order in tests. Use an explicit Setup() or NewService() pattern instead.


**Fix:** Move initialization to an explicit constructor or Setup function

---

#### 🟡 Line 22: go/go-string-tolower-compare

```go
    19 | 	}
    20 | 
    21 | 	// Builtin: string comparison without EqualFold
>  22 | 	if strings.ToLower(name) == "admin" { // expect: go-string-tolower-compare
    23 | 		return "admin dashboard"
    24 | 	}
    25 | 
```

**MEDIUM** | ⚡ performance | Confidence: 85% | Pack: `go`

**What:** strings.ToLower() allocates a new string for comparison — use EqualFold

!!! warning "Why this matters"
    strings.ToLower() creates a new lowercase copy of the string just to compare it. strings.EqualFold() compares case-insensitively without any allocation.


**Fix:** Use strings.EqualFold(a, b) for case-insensitive comparison

=== "Bad"
    ```go
    if strings.ToLower(name) == "admin" {
    ```
=== "Good"
    ```go
    if strings.EqualFold(name, "admin") {
    ```
    *EqualFold is allocation-free*

---

#### 🔵 Line 27: go/go-sprintf-allocation

```go
    24 | 	}
    25 | 
    26 | 	// Builtin: error string comparison
>  27 | 	return fmt.Sprintf("hello %s", name) // expect: go-sprintf-allocation
    28 | }
    29 | 
    30 | func CleanFunction(x int) int {
```

**LOW** | ⚡ performance | Confidence: 50% | Pack: `go`

**What:** fmt.Sprintf allocates a new string per call — consider alternatives in hot paths

!!! warning "Why this matters"
    fmt.Sprintf parses the format string and allocates a new string on every invocation. In hot loops, this creates N allocations that pressure the GC. Not every Sprintf is a problem — only flag this in performance-sensitive paths.


**Fix:** For hot paths, use strings.Builder, strconv.Itoa + concatenation, or pre-allocate

=== "Bad"
    ```go
    key := fmt.Sprintf("cache:%s:%d", prefix, id)
    ```
=== "Good"
    ```go
    key := "cache:" + prefix + ":" + strconv.Itoa(id)
    ```
    *String concatenation avoids format parsing overhead*

---

### `java/BadPatterns.java` `java`

#### 🟡 Line 14: java/java-string-concat-loop

```java
    11 |         // Builtin: string concat in loop
    12 |         String result = "";
    13 |         for (String item : items) {
>  14 |             result += "item: " + item; // expect: java-string-concat-loop
    15 |         }
    16 |         System.out.println("Done: " + result); // expect: java-no-system-out
    17 |         return result;
```

**MEDIUM** | ⚡ performance | Confidence: 60% | Pack: `java`

**What:** String concatenation in loop — O(N^2) due to immutable strings

**Fix:** Use StringBuilder for loop concatenation

=== "Bad"
    ```java
    String result = "";\nfor (String s : items) result += s;
    ```
=== "Good"
    ```java
    StringBuilder sb = new StringBuilder();
for (String s : items) sb.append(s);
    ```

---

#### 🟡 Line 16: java-no-system-out

```java
    13 |         for (String item : items) {
    14 |             result += "item: " + item; // expect: java-string-concat-loop
    15 |         }
>  16 |         System.out.println("Done: " + result); // expect: java-no-system-out
    17 |         return result;
    18 |     }
    19 | 
```

**MEDIUM** | 🎨 style | Confidence: 90%

**What:** Use SLF4J logger instead of System.out

!!! warning "Why this matters"
    System.out bypasses the logging framework. Log output won't appear in structured logs, can't be filtered by level, and won't include context (thread, timestamp, class).


**Fix:** Use log.info(), log.debug(), etc.

=== "Bad"
    ```java
    System.out.println("Processing: " + item);
    ```
=== "Good"
    ```java
    log.info("Processing: {}", item);
    ```

---

#### 🟡 Line 23: java/java-catch-exception

```java
    20 |     public void riskyMethod() {
    21 |         try {
    22 |             loadData();
>  23 |         } catch (Exception e) { // expect: java-catch-exception
    24 |             System.out.println(e.getMessage()); // expect: java-no-system-out
    25 |         }
    26 |     }
```

**MEDIUM** | 🐛 correctness | Confidence: 70% | Pack: `java`

**What:** Catching generic Exception — too broad, may mask bugs

**Fix:** Catch specific exception types

---

#### 🟡 Line 24: java-no-system-out

```java
    21 |         try {
    22 |             loadData();
    23 |         } catch (Exception e) { // expect: java-catch-exception
>  24 |             System.out.println(e.getMessage()); // expect: java-no-system-out
    25 |         }
    26 |     }
    27 | 
```

**MEDIUM** | 🎨 style | Confidence: 90%

**What:** Use SLF4J logger instead of System.out

!!! warning "Why this matters"
    System.out bypasses the logging framework. Log output won't appear in structured logs, can't be filtered by level, and won't include context (thread, timestamp, class).


**Fix:** Use log.info(), log.debug(), etc.

=== "Bad"
    ```java
    System.out.println("Processing: " + item);
    ```
=== "Good"
    ```java
    log.info("Processing: {}", item);
    ```

---

### `python/bad_patterns.py` `python`

#### 🟡 Line 8: no-star-import

```python
     5 | and no unexpected findings appear.
     6 | """
     7 | import logging
>   8 | from utils import *  # expect: no-star-import
     9 | 
    10 | logger = logging.getLogger(__name__)
    11 | 
```

**MEDIUM** | 🎨 style | Confidence: 95%

**What:** Star imports pollute namespace and break static analysis

!!! warning "Why this matters"
    Star imports make it impossible to determine where a name came from without running the code. They also prevent dead-code detection and auto-completion from working correctly.


**Fix:** Import specific names: from module import Class, function

---

#### 🟡 Line 16: no-print-debugging

```python
    13 | def process_items(items: list, config: dict) -> None:
    14 |     """Process items with several bad patterns."""
    15 |     # Team preference: no print debugging
>  16 |     print(f"Starting with {len(items)} items")  # expect: no-print-debugging
    17 | 
    18 |     # Team preference: no bare dict access
    19 |     api_key = config['api_key']  # expect: no-bare-dict-access
```

**MEDIUM** | 🎨 style | Confidence: 85%

**What:** Use logger instead of print() — prints are stripped in CI

!!! warning "Why this matters"
    Our CI pipeline redirects stdout to /dev/null. print() calls are invisible in production. Use the project logger which writes to both stdout and the structured log file.


**Fix:** Replace with logger.info(), logger.debug(), etc.

=== "Bad"
    ```python
    print(f"Processing {item}")
    ```
=== "Good"
    ```python
    logger.info("Processing %s", item)
    ```

---

#### 🟡 Line 25: no-print-debugging

```python
    22 |     logger.info(f"Using key {api_key[:4]}...")  # expect: no-string-format-logging
    23 | 
    24 |     for item in items:
>  25 |         print(item.name)  # expect: no-print-debugging
    26 |         status = config['default_status']  # expect: no-bare-dict-access
    27 | 
    28 | 
```

**MEDIUM** | 🎨 style | Confidence: 85%

**What:** Use logger instead of print() — prints are stripped in CI

!!! warning "Why this matters"
    Our CI pipeline redirects stdout to /dev/null. print() calls are invisible in production. Use the project logger which writes to both stdout and the structured log file.


**Fix:** Replace with logger.info(), logger.debug(), etc.

=== "Bad"
    ```python
    print(f"Processing {item}")
    ```
=== "Good"
    ```python
    logger.info("Processing %s", item)
    ```

---

#### 🔵 Line 19: no-bare-dict-access

```python
    16 |     print(f"Starting with {len(items)} items")  # expect: no-print-debugging
    17 | 
    18 |     # Team preference: no bare dict access
>  19 |     api_key = config['api_key']  # expect: no-bare-dict-access
    20 | 
    21 |     # Team preference: no f-string in logger
    22 |     logger.info(f"Using key {api_key[:4]}...")  # expect: no-string-format-logging
```

**LOW** | 🐛 correctness | Confidence: 60%

**What:** Use .get() for dict access — bare [] throws KeyError on missing keys

!!! warning "Why this matters"
    In our data pipeline, configs and API responses frequently have optional keys. Bare dict[key] access crashes on missing keys. Use .get(key, default) for resilient access.


**Fix:** Use config.get('key', default) instead of config['key']

=== "Bad"
    ```python
    name = config['username']
    ```
=== "Good"
    ```python
    name = config.get('username', 'anonymous')
    ```

---

#### 🔵 Line 22: no-string-format-logging

```python
    19 |     api_key = config['api_key']  # expect: no-bare-dict-access
    20 | 
    21 |     # Team preference: no f-string in logger
>  22 |     logger.info(f"Using key {api_key[:4]}...")  # expect: no-string-format-logging
    23 | 
    24 |     for item in items:
    25 |         print(item.name)  # expect: no-print-debugging
```

**LOW** | ⚡ performance | Confidence: 80%

**What:** Use lazy % formatting in logger calls, not f-strings

!!! warning "Why this matters"
    f-strings are evaluated immediately even if the log level is disabled. Logger % formatting (logger.info("x=%s", x)) is lazy — the string is only formatted if the message will actually be emitted.


**Fix:** Use logger.info("Processing %s", item) not logger.info(f"Processing {item}")

=== "Bad"
    ```python
    logger.debug(f"Loaded {len(items)} items")
    ```
=== "Good"
    ```python
    logger.debug("Loaded %d items", len(items))
    ```

---

#### 🔵 Line 26: no-bare-dict-access

```python
    23 | 
    24 |     for item in items:
    25 |         print(item.name)  # expect: no-print-debugging
>  26 |         status = config['default_status']  # expect: no-bare-dict-access
    27 | 
    28 | 
    29 | def calculate_total(prices: list[float]) -> float:
```

**LOW** | 🐛 correctness | Confidence: 60%

**What:** Use .get() for dict access — bare [] throws KeyError on missing keys

!!! warning "Why this matters"
    In our data pipeline, configs and API responses frequently have optional keys. Bare dict[key] access crashes on missing keys. Use .get(key, default) for resilient access.


**Fix:** Use config.get('key', default) instead of config['key']

=== "Bad"
    ```python
    name = config['username']
    ```
=== "Good"
    ```python
    name = config.get('username', 'anonymous')
    ```

---

### `rust/bad_patterns.rs` `rust`

#### 🟡 Line 9: rs-no-expect-in-lib

```rust
     6 | 
     7 | pub fn load_config(path: &str) -> String {
     8 |     // Team preference: library code should return Result, not expect
>   9 |     let content = fs::read_to_string(path).expect("failed to read config"); // expect: rs-no-expect-in-lib
    10 |     content
    11 | }
    12 | 
```

**MEDIUM** | 🐛 correctness | Confidence: 70%

**What:** Library code should return Result, not expect/panic

!!! warning "Why this matters"
    .expect() panics when the Result is Err, crashing the caller. Library code should propagate errors with ? so callers decide how to handle failures.


**Fix:** Use the ? operator: let value = result?;

=== "Bad"
    ```rust
    let config = fs::read_to_string("config.toml").expect("config missing");
    ```
=== "Good"
    ```rust
    let config = fs::read_to_string("config.toml")?;
    ```

---

#### 🔵 Line 15: rust/rs-clone-in-loop

```rust
    12 | 
    13 | pub fn process(data: &[u8]) -> Vec<u8> {
    14 |     // Builtin: clone in potential hot path
>  15 |     let copy = data.to_vec().clone(); // expect: rs-clone-in-loop
    16 |     copy
    17 | }
    18 | 
```

**LOW** | ⚡ performance | Confidence: 40% | Pack: `rust`

**What:** clone() in potential hot path — deep copy may be expensive

**Fix:** Use references or Cow<T> to avoid unnecessary cloning

---

### `typescript/bad_patterns.ts` `typescript`

#### 🟡 Line 10: typescript/ts-await-in-loop

```typescript
     7 | async function loadAll(ids: string[]) {
     8 |   // Builtin: sequential await in loop
     9 |   for (const id of ids) {
>  10 |     const data = await fetchUser(id); // expect: ts-await-in-loop
    11 |     console.log(data); // expect: ts-console-log
    12 |   }
    13 | }
```

**MEDIUM** | ⚡ performance | Confidence: 55% | Pack: `typescript`

**What:** Possible sequential await in loop — requests may execute one at a time

!!! warning "Why this matters"
    Using await inside a for loop makes each iteration wait for the previous one to complete. If the operations are independent, they can run in parallel with Promise.all(), potentially reducing total time by N×.


**Fix:** Collect promises and use Promise.all() for independent operations

=== "Bad"
    ```typescript
    for (const id of ids) {
  const data = await fetch(id);
}
    ```
=== "Good"
    ```typescript
    const results = await Promise.all(ids.map(id => fetch(id)));
    ```
    *Promise.all runs all fetches concurrently*

---

#### 🟡 Line 17: ts-no-any-cast

```typescript
    14 | 
    15 | function getStatus(response: unknown): string {
    16 |   // Team preference: no cast to any
>  17 |   const data = response as any; // expect: ts-no-any-cast
    18 |   return data.status;
    19 | }
    20 | 
```

**MEDIUM** | 🐛 correctness | Confidence: 90%

**What:** Don't cast to any — use proper type narrowing

!!! warning "Why this matters"
    Casting to `any` silently disables all type checking for that value. Bugs that TypeScript would catch at compile time become runtime errors. Use type guards, unknown, or proper interface narrowing.


**Fix:** Use type guards (if 'key' in obj), unknown, or proper interfaces

=== "Bad"
    ```typescript
    const data = response as any
    ```
=== "Good"
    ```typescript
    const data: ApiResponse = response as ApiResponse
    ```

---

#### ⚪ Line 11: typescript/ts-console-log

```typescript
     8 |   // Builtin: sequential await in loop
     9 |   for (const id of ids) {
    10 |     const data = await fetchUser(id); // expect: ts-await-in-loop
>  11 |     console.log(data); // expect: ts-console-log
    12 |   }
    13 | }
    14 | 
```

**INFO** | 🎨 style | Confidence: 60% | Pack: `typescript`

**What:** console.log left in code — use proper logging or remove

**Fix:** Use a structured logger or remove debug statements

---

## Available Language Packs

- **go** — 12 rules (5x performance, 4x security, 2x correctness, 1x suspicious)
- **java** — 5 rules (2x performance, 1x security, 1x correctness, 1x style)
- **python** — 6 rules (2x correctness, 2x performance, 1x complexity, 1x style)
- **rust** — 4 rules (2x correctness, 1x security, 1x performance)
- **typescript** — 5 rules (3x style, 1x correctness, 1x performance)

## Custom Team Rules

- 🟡 **no-print-debugging** — Use logger instead of print() — prints are stripped in CI
- 🔵 **no-bare-dict-access** — Use .get() for dict access — bare [] throws KeyError on missing keys
- 🟡 **no-star-import** — Star imports pollute namespace and break static analysis
- 🔵 **no-string-format-logging** — Use lazy % formatting in logger calls, not f-strings
- 🟠 **go-no-panic** — Don't panic — return errors instead
- 🟡 **go-no-init-function** — Avoid init() — use explicit initialization for testability
- 🟡 **ts-no-any-cast** — Don't cast to any — use proper type narrowing
- 🟡 **rs-no-expect-in-lib** — Library code should return Result, not expect/panic
- 🟡 **java-no-system-out** — Use SLF4J logger instead of System.out
