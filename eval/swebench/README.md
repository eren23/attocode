# SWE-bench Evaluation

## Setup

1. Install the datasets library:
   ```bash
   uv add datasets
   ```

2. Run a canary test (3 instances):
   ```bash
   python -m eval.swebench run --limit 3 --debug
   ```

3. Run full evaluation:
   ```bash
   python -m eval.swebench run --limit 300
   ```

4. Grade results:
   ```bash
   python -m eval.swebench grade --run-id <run_id>
   ```

5. Compare against leaderboard:
   ```bash
   python -m eval.swebench leaderboard --run-id <run_id>
   ```

## Dataset

Uses `princeton-nlp/SWE-bench_Lite` from HuggingFace (300 instances).

Alternatively, provide a local JSONL file:
```bash
python -m eval.swebench run --dataset path/to/instances.jsonl --limit 10
```

## Published Leaderboard (March 2026)

| Model | Pass Rate |
|-------|-----------|
| Claude Opus 4.5 | 80.9% |
| Claude Opus 4.6 | 80.8% |
| Gemini 3.1 Pro | 80.6% |
| GPT-5.2 | 80.0% |
| Claude Sonnet 4.6 | 79.6% |

## Architecture

- `adapter.py` — AttoswarmSWEBenchFactory (bridges SwarmOrchestrator to eval harness)
- `dataset.py` — Dataset loading (HuggingFace or JSONL)
- `grader.py` — Test-based verification (local or official)
- `efficiency.py` — Swarm performance metrics
- `config.py` — Default configuration (2M tokens, $5 cost limit)
- `cli.py` — CLI with run/grade/compare/efficiency/leaderboard commands
- `prompt.py` — Goal and instruction generation per instance
- `report.py` — Report generation
