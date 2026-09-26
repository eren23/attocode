# Calibration demo and local jev adoption

The saved September 20, 2026 data and media are historical evidence. Rebuilding
the page makes no model calls. The current source review is separate from the
original model answers: 78 of the 82 repository examples are false positives,
two remain unresolved, and two identify the same permissive CORS default.
These are source-review dispositions, not independent ground truth for a
general-purpose calibration benchmark.

## Rebuild and view

From the repository root:

```sh
.venv/bin/python -m eval.rule_accuracy.demo.build
.venv/bin/python -m eval.rule_accuracy.demo.serve --port 8933
```

Open http://127.0.0.1:8933/calibration-demo/calibration.html. The server binds
only to loopback and serves text as UTF-8. `--data-dir` and `--output-dir` on
the builder select explicit snapshot/output directories. The original MP4,
poster, and eight screenshots stay in the ignored `.playwright-mcp/` directory;
`manifest.json` records their checksums. Media is not embedded in Git or
downloaded automatically. If copying to another machine, copy those media
files separately and retain their relative locations.

The page intentionally retains the recorded scores and timings. Its legacy
ECE calculation uses bin midpoints, not mean predicted confidence. The corpus
labels match particular rule IDs, so an overlapping valid rule can be counted
as a false positive. Earlier source context was incomplete and retained some
`ok`/`nosec` annotations. Do not use these values as an unbiased deployment
acceptance threshold or mix them with new runs.

## Use jev locally

The ignored `.attocode/config.toml` enables only this workspace:

```toml
[confidence]
scorer = "jev"
mode = "live"
backend = "openrouter"
```

Credentials stay in the existing root `.env` or process environment. Explicit
feature-flag overrides take precedence over environment settings, which take
precedence over the workspace file. `ATTOCODE_FLAG_CONFIDENCE=off` disables
scoring; `ATTOCODE_FLAG_CONFIDENCE_MODE=shadow` records estimates without
changing filtering. Backend selection respects `JEV_BACKEND` and local-only
mode. Other workspaces remain off/shadow unless separately configured.

Use the existing `analyze`, full `review_change`, or `ci_scan` tools. The Python
example pack is activated locally. The live scorer considers rules below
their original confidence threshold and receives surrounding source context.
It makes at most 25 calls per scan with 16 workers. Skipped, unavailable, and
failed estimates retain baseline confidence and are counted in the output.
Existing Python MCP processes must reconnect to load changed source; the
verification command below launches a fresh gateway using the same tool path.

```sh
.venv/bin/python -m eval.rule_accuracy.demo.scan --score --verify-tool
```

This explicitly sends redacted context for the 82 saved examples plus a small
tool smoke scan to the configured jev endpoint. It creates a new timestamped
directory under `.attocode/reports/jev/`, including `REPORT.md`, reviewed
`findings.json`, the unreviewed `inventory.json`, source/revision metadata, and
live/outage tool responses. No feedback labels or rule disables are applied
automatically. Omit `--score --verify-tool` for a network-free inventory and
report. `triage.json` holds reviewed decisions with evidence and acceptance
criteria; new or ambiguous locations remain unresolved.

## Fresh measurements and captures

Keep new runs in a separate directory. These explicit commands make provider
calls; `dump`, `record`, and `real` run both scorers:

```sh
.venv/bin/python -m eval.rule_accuracy.demo.dump --output-dir .playwright-mcp/fresh-data
.venv/bin/python -m eval.rule_accuracy.demo.record --output-dir .playwright-mcp/fresh-data
.venv/bin/python -m eval.rule_accuracy.demo.real --output-dir .playwright-mcp/fresh-data
.venv/bin/python -m eval.rule_accuracy.demo.stats --output-dir .playwright-mcp/fresh-data
.venv/bin/python -m eval.rule_accuracy.demo.prepare --directory .playwright-mcp/fresh-data
```

`prepare` creates the compact chart and race inputs. Fresh source context is
enriched and benchmark annotations are stripped before scoring. Review and
update the narrative, fixed timing labels, dataset date, and media provenance
before using fresh data in the historical page template. A refresh is a new
experiment; it is not expected to reproduce provider scores bit for bit.

For local capture, the optional Python Playwright package, its Chromium
browser, and FFmpeg are required. Start the server, then:

```sh
.venv/bin/python -m eval.rule_accuracy.demo.shots --url http://127.0.0.1:8933/calibration-demo/calibration.html --output-dir .playwright-mcp/new-shots
.venv/bin/python -m eval.rule_accuracy.demo.film --url http://127.0.0.1:8933/calibration-demo/calibration.html --output-dir .playwright-mcp/new-recording
```

The capture scripts use the real page. They write new files instead of
replacing the historical assets. The film command prints its WebM path;
convert that explicit file with `ffmpeg -i <recording.webm> -c:v libx264 -pix_fmt
yuv420p -movflags +faststart <new-recording.mp4>`. Review the new captions,
timings, and cases before replacing any media reference.

## Verification

Run focused tests with ambient live scoring disabled:

```sh
ATTOCODE_FLAG_CONFIDENCE=off .venv/bin/python -m pytest tests/unit/code_intel/test_confidence.py tests/unit/code_intel/test_confidence_adoption.py tests/unit/code_intel/test_ci_runner.py tests/unit/eval/test_rule_accuracy.py tests/unit/eval/test_calibration_demo.py -q
```

The adoption tests explicitly enable fake providers in isolated workspaces;
they check redaction, context, threshold promotion, configuration precedence,
concurrent isolation, invalid responses, cap/fallback visibility, and offline
rule assertions. Browser checks cover both explorer filters, the long CLI
description, UTF-8, race replay, and MP4 playback.
