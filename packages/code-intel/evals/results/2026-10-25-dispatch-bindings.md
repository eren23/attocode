# Maintained experiment dispatcher bindings

The dispatcher derived an operator module from the experiment name. An earlier context trial aborted before issuing queries after a naming mismatch. Operator bodies remain responsible for their frozen designs; this correction makes their registration independently testable.

The dispatcher now binds each external operator explicitly. Before importing it, the resolved module must match its declared repository source; the imported module is checked again. Its `run(root)` must accept the positional root and execute synchronously. Coroutine and generator functions, including callable objects, are rejected before their bodies run. Unknown bindings and import errors produce an explicit binding error; the original exception remains its cause.

Validation remains inside the existing engine-guarded, supervised controller. Maintained preflight qualifies every registered target without running its body and checks workflow choices against registrations. This catches future binding mistakes in CI before a manual launch. It does not move arbitrary imports into unbounded parent/setup code or change experiment limits, fixtures, decisions, retries or source identity policy.

| Online control | Cases | Positive | Declared feature-absence failures | Seconds |
|---|---:|---:|---:|---:|
| [red-1](https://github.com/eren23/attocode/actions/runs/40227104023) | 327 | 309 | 18 | 26.789 |
| [shape-red-1](https://github.com/eren23/attocode/actions/runs/40227400476) | 331 | 327 | 4 | 27.325 |
| [green-1](https://github.com/eren23/attocode/actions/runs/40227553074) | 331 | 331 | 0 | 26.500 |

The first RED retains 18 exact binding assertions. The separate shape RED proves four generator forms could skip their body; its other 327 cases pass, including all original binding controls. The final 331 cases pass without failures, errors or skips. Every control workflow treats only its prospectively declared assertions as successful RED data; unexpected failures remain incomplete. These are synthetic operator-import/body controls, with no native, corpus retrieval or scored trial.

Keep 26 new regressions in maintained preflight (331 cases) and the required normal-CI inventory (344 regressions). They exercise real temporary modules, explicit aliases, undeclared conventional names, shadowed source, original import errors, missing/noncallable/wrong-signature/async/generator entrypoints, compatible root signatures, the original engine guard, and all maintained target bindings without executing heavy bodies.

All 349 product runtime files, version 0.1.19 and dependencies equal the published baseline. This is harness-only integration and publishes no package. No historical OCaml/Rust cause, ranking/relevance improvement or speed benefit is claimed. Temporary controller/design/choice/registry wiring is retired; original evidence remains.

The [evidence archive](2026-10-25-dispatch-bindings.tar.gz) preserves three original ZIPs, four executed/baseline source maps and both equal 349-file engine maps. Every original and Git source byte was replayed independently using retained data only. SHA-256 `d4adf4ffc7fa5e7c9b145646c50b9d32f5a86042ea6f354bb2e95ccc5f1d38ab`; 2396595 bytes, 695 members. Normal 17 checks and all artifact/install/preflight/image, reviewed/CI/merged full-tree, postmerge and cleanup gates remain mandatory.
