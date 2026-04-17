# eval/codewm — Code World Model Experiment Ground

**Status: EXPERIMENTAL** — PyTorch backend, will be replaced by compiled binary.

This is the sandbox for testing VICReg/JEPA-trained code world model checkpoints
against real Python codebases. Nothing here is wired into the production attocode
source tree (`src/attocode/`). When the model proves useful enough and the lighter
binary backend lands, the good parts graduate into `src/attocode/code_intel/`.

## What's here

| File | Purpose |
|---|---|
| `backend.py` | `CodeWMBackend` Protocol + `CodeWMConfig` — the swap interface. Implement this protocol for any new backend (PyTorch, Rust binary, ONNX, etc.) |
| `pytorch_backend.py` | Temporary PyTorch backend. Dynamically imports model classes from `~/.crucible-hub/taps/crucible-community-tap/architectures/` (code_wm + wm_base). Loads `.pt` checkpoints. Will die when binary replaces it. |
| `cli.py` | Smoke test: load checkpoint, run encode + predict, print latencies |
| `eval_codeintel.py` | Real-world assessment: file similarity, edit prediction (with real 15-dim action vectors from `ast_diff.py`), latent retrieval |

## Dependencies

- **PyTorch** — `pip install torch` (not in attocode's deps, intentionally)
- **Crucible taps** — model source at `~/.crucible-hub/taps/crucible-community-tap/architectures/` (code_wm.py, wm_base.py, ast_tokenizer.py, diff_tokenizer.py, ast_diff.py). Override with `--src` or `CODEWM_SRC` env var.
- **Checkpoint** — `.pt` file with keys: `model_state_dict`, `config`, `step`, `loss`

## Usage

All commands run from the project root:

```bash
# Smoke test — loads checkpoint, runs encode/predict, prints shapes + timings
PYTHONPATH=. uv run python -m eval.codewm smoke --ckpt /tmp/vicreg_sota_step14500.pt

# Smoke test with real diff tokens (uses diff_tokenizer from taps)
PYTHONPATH=. uv run python -m eval.codewm smoke --ckpt /tmp/vicreg_sota_step14500.pt --real-tokens

# Full assessment on a Python repo
PYTHONPATH=. uv run python -m eval.codewm.eval_codeintel \
    --ckpt /tmp/vicreg_sota_step14500.pt \
    --repo /path/to/python/repo \
    --max-files 40
```

## Current checkpoint

SOTA-MEDIUM phase 9, step 14500 (`/tmp/vicreg_sota_step14500.pt`, 12MB):
- model_dim=128, vocab_size=700, action_dim=15, encoder_loops=3, num_loops=6
- Trained with VICReg loss + attn pooling
- loss=0.019, best_loss=0.015

## Assessment results (attocode codebase, 2026-04-17)

**Encoder quality — strong:**
- File similarity mean=0.87, std=0.11. API route files cluster (0.99), structurally different files separate (0.54).
- Directory clustering: intra-dir 0.90 > inter-dir 0.86 (+0.04 separation).
- Retrieval hit@3: 80%, hit@5: 100%.

**Predictor — weak on this repo:**
- Real action LIFT over random: +0.01 (noisy). Edits in this repo are small (cos(before,after) ≈ 0.999), leaving almost no delta for the predictor to learn from.
- Some individual edits show strong lift (+0.05-0.06) when structural change is larger.
- Needs distribution-matched data or bigger edits to properly evaluate.

## Backend swap plan

`CodeWMBackend` in `backend.py` is a Protocol with three methods:
- `encode_state(token_ids) -> latent`
- `encode_action(action) -> latent`
- `predict_next_state(state_z, action_z) -> latent`

All numpy-in / numpy-out. When the compiled binary is ready, implement a new backend
(e.g. `binary_backend.py`) that shells out or uses FFI, drop `pytorch_backend.py`.

## What this is NOT

- Not a provider (this isn't an LLM, it's a latent-space code state predictor)
- Not production code (nothing in `src/attocode/` imports from here)
- Not a training harness (use crucible for training, this is inference + eval only)
