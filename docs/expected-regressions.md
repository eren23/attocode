# Checking an expected regression in Actions

Normal PR, main and release workflows remain strict. Use **Expected regression**
before opening a PR when a new tests-only branch deliberately demonstrates a bug.
Do not push an intentionally failing PR to obtain RED evidence.

1. Commit the new tests and a prospective contract under `.github/regressions/`.
   Push the feature branch without opening a PR.
2. Dispatch the workflow on that branch with the contract path:

   ```sh
   gh workflow run expected-regression.yml --ref fix/my-regression \
     -f contract=.github/regressions/my-regression.json
   ```
3. Download `expected-regression-evidence`. Read `proof.json`, original pytest
   XML/log, source fingerprints and (for native runs) complete native evidence.
   A successful workflow means **the declared regression was observed**. It does
   not mean the product passes. Preserve this evidence before implementing.
4. Fix the producer, retaining the same test expectations. Open the completed PR
   and require all normal checks at its exact final head before merging.

The contract declares the complete testcase inventory and exactly which cases
must fail. IDs use the test module basename (without `.py`), followed by `::`
and the literal pytest testcase name, including parameter brackets:

```json
{
  "schema_version": 1,
  "profile": "unit",
  "paths": ["packages/code-intel/tests/test_example.py"],
  "cases": ["test_example::test_receiver", "test_example::test_control"],
  "failures": {
    "test_example::test_receiver": {
      "message": "REGRESSION: receiver identity",
      "properties": {"qualified_input": "true"}
    }
  }
}
```

Set qualification properties with pytest's `record_property` only after the
input has passed its syntax/source/fixture guards. Raise an `AssertionError`
with the declared message at the semantic assertion. The failure message must
begin `AssertionError: ` followed by that marker. Every other declared case
must pass. Cases cannot skip or produce setup/teardown errors. Missing,
unexpected or duplicate cases, unexpected passes, crashes, collection errors,
timeouts, changed sources or failed cleanup reject the run normally.

`profile: "native"` runs the fixed acquired-grammar gate instead of selected
unit files; set `paths: []` and include every case in
`packages/code-intel/scripts/optional_grammar_cases.json`. This profile also
requires unchanged grammar identities, unchanged sources and successful owned
scratch cleanup. Its original gate report remains `incomplete` with rejected
coverage because the declared semantic regression occurred.

The workflow accepts no shell command. Unit paths must be existing nonsymlink
Python test files directly within the code-intel test tree. Each run uses a
fresh runner temporary directory, bounded commands and read-only repository
permissions. Installation/acquisition failures and final strict gates still
produce normal failed runs; this workflow does not alter notification settings.
