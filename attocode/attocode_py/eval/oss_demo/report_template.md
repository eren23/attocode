# Codebase Intelligence Demo Report

## Executive Summary
- Objective:
- Run date:
- Agents compared: Codex CLI, Claude Code, Cursor Composer 1.5
- Repositories: microsoft/vscode, django/django, pytorch/pytorch
- Key finding:

## Comparative Scorecard
| Agent | Completion | Evidence | Correctness | Latency | Cost Proxy | Tool Efficiency | Notes |
|---|---:|---:|---:|---:|---:|---:|---|
| Codex CLI |  |  |  |  |  |  |  |
| Claude Code |  |  |  |  |  |  |  |
| Cursor Composer 1.5 |  |  |  |  |  |  |  |

## Per-Repository Observations
### microsoft/vscode
- Strong outcomes:
- Weak outcomes:
- Best agent for this archetype:

### django/django
- Strong outcomes:
- Weak outcomes:
- Best agent for this archetype:

### pytorch/pytorch
- Strong outcomes:
- Weak outcomes:
- Best agent for this archetype:

## Ablation: With vs Without Code-Intel Tools
- Sample repo: django/django
- Delta in completion quality:
- Delta in latency:
- Delta in error rate:
- Bottom line:

## Convincing Skeptics: Practical Value Statement
Cheap/fast agents become materially more useful on large repositories when
high-signal structural tools (`bootstrap`, `relevant_context`,
`impact_analysis`, `hotspots`) replace blind file-grepping loops.

## Reproducibility Appendix
- Manifest path: `eval/oss_demo/run_manifest.yaml`
- Results path: `eval/oss_demo/results.jsonl`
- Summary command:
  ```bash
  python -m eval.oss_demo summarize \
    --manifest eval/oss_demo/run_manifest.yaml \
    --results eval/oss_demo/results.jsonl \
    --out eval/oss_demo/report.md
  ```
