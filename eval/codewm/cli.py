"""CodeWM smoke test CLI.

Usage:
    python -m eval.codewm smoke --ckpt /tmp/vicreg_sota_step14500.pt
    python -m eval.codewm smoke --ckpt /tmp/vicreg_sota_step14500.pt --real-tokens

The --real-tokens flag uses the diff_tokenizer from crucible taps to encode
a real code snippet instead of random token IDs.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np


def _resolve_taps_src(override: str | None) -> str:
    if override:
        return override
    default = Path.home() / ".crucible-hub" / "taps" / "crucible-community-tap" / "architectures"
    if default.exists():
        return str(default)
    raise FileNotFoundError(
        f"Crucible taps not found at {default}. Set --src or CODEWM_SRC."
    )


def _tokenize_real_snippet(src_path: str, max_len: int, vocab_size: int) -> np.ndarray:
    """Use diff_tokenizer from taps to encode a real code change."""
    taps_root = Path(src_path).parent  # up from architectures/ to tap root
    tokenizer_path = taps_root / "collectors" / "diff_tokenizer.py"
    if not tokenizer_path.exists():
        print(f"  diff_tokenizer not found at {tokenizer_path}, falling back to random")
        rng = np.random.default_rng(42)
        return rng.integers(0, vocab_size, size=(1, max_len))

    import importlib.util
    spec = importlib.util.spec_from_file_location("diff_tokenizer", str(tokenizer_path))
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    # A tiny real Python edit
    old_code = "def greet(name):\n    return 'hello ' + name\n"
    new_code = "def greet(name: str) -> str:\n    return f'hello {name}'\n"

    tokens = mod.tokenize_diff(old_code, new_code, max_len=max_len)
    return np.array(tokens, dtype=np.int64).reshape(1, -1)


def cmd_smoke(args: argparse.Namespace) -> None:
    from eval.codewm.pytorch_backend import PyTorchCodeWMBackend

    print("=" * 60)
    print("CodeWM Smoke Test (EXPERIMENTAL)")
    print("=" * 60)

    src = _resolve_taps_src(args.src)
    print(f"  ckpt: {args.ckpt}")
    print(f"  src:  {src}")
    print()

    t0 = time.perf_counter()
    backend = PyTorchCodeWMBackend(
        ckpt_path=args.ckpt,
        src_path=src,
        device=args.device,
        pool_mode="attn",
    )
    load_ms = (time.perf_counter() - t0) * 1000
    print(f"\n  Model loaded in {load_ms:.0f}ms")

    cfg = backend.config
    seq_len = min(64, cfg["max_seq_len"])
    vocab_size = cfg["vocab_size"]
    action_dim = cfg["action_dim"]

    # -- Encode state --
    if args.real_tokens:
        print("\n  [encode_state] Using real diff tokens:")
        tokens = _tokenize_real_snippet(src, seq_len, vocab_size)
        print(f"    tokens shape={tokens.shape}, first 10: {tokens[0, :10].tolist()}")
    else:
        rng = np.random.default_rng(42)
        tokens = rng.integers(0, vocab_size, size=(1, seq_len))
        print(f"\n  [encode_state] Random tokens shape={tokens.shape}")

    t0 = time.perf_counter()
    state_z = backend.encode_state(tokens)
    enc_ms = (time.perf_counter() - t0) * 1000
    print(f"    -> latent: shape={state_z.shape}, norm={np.linalg.norm(state_z):.4f}, {enc_ms:.1f}ms")

    # -- Encode action --
    rng2 = np.random.default_rng(7)
    action = rng2.standard_normal((1, action_dim)).astype(np.float32)
    print(f"\n  [encode_action] Random action shape={action.shape}")

    t0 = time.perf_counter()
    action_z = backend.encode_action(action)
    act_ms = (time.perf_counter() - t0) * 1000
    print(f"    -> latent: shape={action_z.shape}, norm={np.linalg.norm(action_z):.4f}, {act_ms:.1f}ms")

    # -- Predict next state --
    print(f"\n  [predict_next_state]")
    t0 = time.perf_counter()
    next_z = backend.predict_next_state(state_z, action_z)
    pred_ms = (time.perf_counter() - t0) * 1000
    cos_sim = float(
        np.dot(state_z.flatten(), next_z.flatten())
        / (np.linalg.norm(state_z) * np.linalg.norm(next_z) + 1e-8)
    )
    print(f"    -> latent: shape={next_z.shape}, norm={np.linalg.norm(next_z):.4f}, {pred_ms:.1f}ms")
    print(f"    cos_sim(state, predicted_next): {cos_sim:.4f}")

    # -- Batch test --
    batch = 8
    tokens_batch = np.random.default_rng(0).integers(0, vocab_size, size=(batch, seq_len))
    t0 = time.perf_counter()
    z_batch = backend.encode_state(tokens_batch)
    batch_ms = (time.perf_counter() - t0) * 1000
    print(f"\n  [batch={batch}] encode_state: shape={z_batch.shape}, {batch_ms:.1f}ms ({batch_ms/batch:.1f}ms/sample)")

    print("\n" + "=" * 60)
    print("  PASS — all operations completed successfully")
    print("=" * 60)


def main() -> None:
    p = argparse.ArgumentParser(prog="codewm", description="CodeWM test utilities")
    sub = p.add_subparsers(dest="cmd")

    smoke = sub.add_parser("smoke", help="Smoke test: load checkpoint, run encode+predict")
    smoke.add_argument("--ckpt", required=True, help="Path to .pt checkpoint")
    smoke.add_argument("--src", default=None, help="Path to architectures/ dir (default: ~/.crucible-hub/taps/...)")
    smoke.add_argument("--device", default="cpu")
    smoke.add_argument("--real-tokens", action="store_true", help="Use diff_tokenizer for real code tokens")

    args = p.parse_args()
    if args.cmd == "smoke":
        cmd_smoke(args)
    else:
        p.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
