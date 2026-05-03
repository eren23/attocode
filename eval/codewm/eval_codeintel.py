"""Assess CodeWM on real Python codebases.

Tests three capabilities:
1. Similarity: do related files cluster in latent space?
2. Edit prediction: does predictor match real git edits?
3. Retrieval: can latent similarity find related code?

Usage:
    python -m eval.codewm.eval_codeintel \
        --ckpt /tmp/vicreg_sota_step14500.pt \
        --repo /path/to/python/repo
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_taps_modules(taps_root: Path):
    """Load AST tokenizer, diff tokenizer, and ast_diff from crucible taps."""
    collectors = taps_root / "collectors"
    modules = {}
    for name, filename in [
        ("ast_tokenizer", "ast_tokenizer.py"),
        ("diff_tokenizer", "diff_tokenizer.py"),
        ("ast_diff", "ast_diff.py"),
    ]:
        filepath = collectors / filename
        if not filepath.exists():
            raise FileNotFoundError(f"Required tap module not found: {filepath}")
        spec = importlib.util.spec_from_file_location(name, str(filepath))
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        modules[name] = mod
    return modules["ast_tokenizer"], modules["diff_tokenizer"], modules["ast_diff"]


def _collect_python_files(repo: Path, max_files: int = 50) -> list[Path]:
    """Gather Python files, prefer src/ and core modules."""
    candidates = sorted(repo.rglob("*.py"))
    # Filter out tests, __pycache__, migrations, vendored
    filtered = [
        p for p in candidates
        if "__pycache__" not in str(p)
        and "node_modules" not in str(p)
        and ".git" not in str(p)
        and "migrations" not in str(p)
        and p.stat().st_size > 200  # skip near-empty files
        and p.stat().st_size < 50_000  # skip huge generated files
    ]
    # Prefer src/ files
    src_files = [p for p in filtered if "/src/" in str(p)]
    other_files = [p for p in filtered if "/src/" not in str(p)]
    result = src_files[:max_files] + other_files[:max(0, max_files - len(src_files))]
    return result[:max_files]


def _git_recent_diffs(repo: Path, n: int = 20, *, min_diff_lines: int = 0) -> list[dict[str, Any]]:
    """Extract recent single-file Python edits from git log.

    Args:
        min_diff_lines: skip edits with fewer changed lines (0 = no filter).
            Use min_diff_lines=10+ to find structural edits where the predictor
            has more signal to work with.
    """
    try:
        # Scan deeper history to find enough qualifying edits
        scan_depth = n * 10 if min_diff_lines > 0 else n * 3
        log = subprocess.run(
            ["git", "log", "--oneline", "--diff-filter=M", "--name-only",
             "--pretty=format:%H", "-n", str(scan_depth), "--", "*.py"],
            cwd=repo, capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    if log.returncode != 0:
        return []

    diffs = []
    lines = log.stdout.strip().split("\n")
    i = 0
    while i < len(lines) and len(diffs) < n:
        commit = lines[i].strip()
        if not commit or len(commit) < 7:
            i += 1
            continue
        i += 1
        files = []
        while i < len(lines) and lines[i].strip() and not (len(lines[i].strip()) >= 7 and all(c in "0123456789abcdef" for c in lines[i].strip())):
            f = lines[i].strip()
            if f.endswith(".py"):
                files.append(f)
            i += 1
        if len(files) == 1:
            fpath = files[0]
            try:
                before = subprocess.run(
                    ["git", "show", f"{commit}~1:{fpath}"],
                    cwd=repo, capture_output=True, text=True, timeout=5,
                )
                after = subprocess.run(
                    ["git", "show", f"{commit}:{fpath}"],
                    cwd=repo, capture_output=True, text=True, timeout=5,
                )
                if before.returncode == 0 and after.returncode == 0:
                    # Check diff size if filter is set
                    if min_diff_lines > 0:
                        diff_stat = subprocess.run(
                            ["git", "diff", "--stat", f"{commit}~1", commit, "--", fpath],
                            cwd=repo, capture_output=True, text=True, timeout=5,
                        )
                        # Parse "N insertions(+), M deletions(-)" from last line
                        stat_line = diff_stat.stdout.strip().split("\n")[-1] if diff_stat.stdout.strip() else ""
                        changes = 0
                        for part in stat_line.split(","):
                            part = part.strip()
                            if "insertion" in part or "deletion" in part:
                                try:
                                    changes += int(part.split()[0])
                                except (ValueError, IndexError):
                                    pass
                        if changes < min_diff_lines:
                            continue

                    diffs.append({
                        "commit": commit[:8],
                        "file": fpath,
                        "before": before.stdout,
                        "after": after.stdout,
                    })
            except subprocess.TimeoutExpired:
                pass

    return diffs


# ---------------------------------------------------------------------------
# Assessment functions
# ---------------------------------------------------------------------------

def assess_similarity(backend, ast_tok, files: list[Path], repo: Path) -> dict[str, Any]:
    """Encode files to latent, compute pairwise cosine similarity matrix."""
    print("\n━━━ 1. FILE SIMILARITY ━━━")

    max_len = min(128, backend.config["max_seq_len"])
    embeddings = []
    names = []

    for f in files:
        try:
            source = f.read_text(errors="replace")
            tokens = ast_tok.ast_tokenize(source, max_len=max_len)
            tokens = np.array(tokens, dtype=np.int64).reshape(1, -1)
            z = backend.encode_state(tokens)
            embeddings.append(z.flatten())
            names.append(str(f.relative_to(repo)))
        except Exception:
            continue

    if len(embeddings) < 4:
        print("  Too few files encoded, skipping")
        return {"n_files": len(embeddings)}

    E = np.stack(embeddings)  # [N, D]
    norms = np.linalg.norm(E, axis=1, keepdims=True) + 1e-8
    E_norm = E / norms
    sim_matrix = E_norm @ E_norm.T  # [N, N]

    # Stats
    mask = ~np.eye(len(embeddings), dtype=bool)
    off_diag = sim_matrix[mask]

    print(f"  Files encoded: {len(embeddings)}")
    print(f"  Pairwise cosine sim: mean={off_diag.mean():.4f}, std={off_diag.std():.4f}, "
          f"min={off_diag.min():.4f}, max={off_diag.max():.4f}")

    # Show top-5 most similar pairs
    n = len(embeddings)
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            pairs.append((sim_matrix[i, j], names[i], names[j]))
    pairs.sort(reverse=True)

    print("\n  Top-5 most similar pairs:")
    for sim, a, b in pairs[:5]:
        a_short = a if len(a) < 50 else "..." + a[-47:]
        b_short = b if len(b) < 50 else "..." + b[-47:]
        print(f"    {sim:.4f}  {a_short}  <->  {b_short}")

    print("\n  Bottom-5 least similar pairs:")
    for sim, a, b in pairs[-5:]:
        a_short = a if len(a) < 50 else "..." + a[-47:]
        b_short = b if len(b) < 50 else "..." + b[-47:]
        print(f"    {sim:.4f}  {a_short}  <->  {b_short}")

    # Group by directory — do files in same dir cluster?
    dir_groups: dict[str, list[int]] = {}
    for idx, name in enumerate(names):
        d = str(Path(name).parent)
        dir_groups.setdefault(d, []).append(idx)

    intra_sims, inter_sims = [], []
    for d, indices in dir_groups.items():
        if len(indices) < 2:
            continue
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                intra_sims.append(sim_matrix[indices[i], indices[j]])
    # Inter = everything not intra
    intra_set = set()
    for d, indices in dir_groups.items():
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                intra_set.add((min(indices[i], indices[j]), max(indices[i], indices[j])))
    for i in range(n):
        for j in range(i + 1, n):
            if (i, j) not in intra_set:
                inter_sims.append(sim_matrix[i, j])

    if intra_sims and inter_sims:
        intra_mean = np.mean(intra_sims)
        inter_mean = np.mean(inter_sims)
        print(f"\n  Directory clustering:")
        print(f"    Intra-dir mean sim: {intra_mean:.4f} ({len(intra_sims)} pairs)")
        print(f"    Inter-dir mean sim: {inter_mean:.4f} ({len(inter_sims)} pairs)")
        print(f"    Separation: {intra_mean - inter_mean:+.4f} {'good' if intra_mean > inter_mean else 'BAD'}")

    return {
        "n_files": len(embeddings),
        "sim_mean": float(off_diag.mean()),
        "sim_std": float(off_diag.std()),
        "intra_dir_mean": float(np.mean(intra_sims)) if intra_sims else None,
        "inter_dir_mean": float(np.mean(inter_sims)) if inter_sims else None,
    }


def assess_edit_prediction(backend, ast_tok, ast_diff_mod, diffs: list[dict], max_len: int = 128) -> dict[str, Any]:
    """Test: does predictor output match real after-state encoding?

    Uses compute_rich_action() from ast_diff.py for real 15-dim action vectors
    instead of random noise — matches the training data format exactly.
    """
    print("\n━━━ 2. EDIT PREDICTION (real action vectors) ━━━")

    if not diffs:
        print("  No git diffs found, skipping")
        return {"n_edits": 0}

    cos_pred_reals = []
    cos_before_afters = []
    cos_random_baselines = []
    l2_dists = []

    for d in diffs:
        try:
            # Tokenize before and after states
            before_tokens = ast_tok.ast_tokenize(d["before"], max_len=max_len)
            after_tokens = ast_tok.ast_tokenize(d["after"], max_len=max_len)

            before_np = np.array(before_tokens, dtype=np.int64).reshape(1, -1)
            after_np = np.array(after_tokens, dtype=np.int64).reshape(1, -1)

            # Encode real states
            z_before = backend.encode_state(before_np).flatten()
            z_after_real = backend.encode_state(after_np).flatten()

            # REAL action: compute_rich_action from ast_diff (15-dim)
            action = ast_diff_mod.compute_rich_action(d["before"], d["after"])
            action_np = action.reshape(1, -1).astype(np.float32)
            action_z = backend.encode_action(action_np).flatten()

            z_predicted = backend.predict_next_state(
                z_before.reshape(1, -1), action_z.reshape(1, -1)
            ).flatten()

            # RANDOM baseline: predict with noise action for comparison
            rng = np.random.default_rng(hash(d["commit"]) % (2**31))
            rand_action = rng.standard_normal((1, backend.config["action_dim"])).astype(np.float32)
            rand_action_z = backend.encode_action(rand_action).flatten()
            z_random_pred = backend.predict_next_state(
                z_before.reshape(1, -1), rand_action_z.reshape(1, -1)
            ).flatten()

            def _cos(a, b):
                return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))

            cos_pred = _cos(z_predicted, z_after_real)
            cos_ba = _cos(z_before, z_after_real)
            cos_rand = _cos(z_random_pred, z_after_real)
            l2 = float(np.linalg.norm(z_predicted - z_after_real))

            cos_pred_reals.append(cos_pred)
            cos_before_afters.append(cos_ba)
            cos_random_baselines.append(cos_rand)
            l2_dists.append(l2)

            # Show action breakdown
            action_desc = []
            if action[0] > 0.5: action_desc.append("ADD")
            elif action[1] > 0.5: action_desc.append("DEL")
            elif action[2] > 0.5: action_desc.append("MOD")
            if action[3] > 0.5: action_desc.append("fn")
            elif action[4] > 0.5: action_desc.append("cls")
            elif action[5] > 0.5: action_desc.append("mod")

            delta = cos_pred - cos_rand
            marker = "+" if delta > 0 else "-"
            print(f"  {d['commit']} {d['file'][:35]:35s} [{','.join(action_desc):8s}] "
                  f"real={cos_pred:+.4f} rand={cos_rand:+.4f} [{marker}{abs(delta):.4f}] "
                  f"bef/aft={cos_ba:+.4f}")

        except Exception as e:
            print(f"  {d['commit']} SKIP: {e}")
            continue

    if cos_pred_reals:
        real_mean = np.mean(cos_pred_reals)
        rand_mean = np.mean(cos_random_baselines)
        lift = real_mean - rand_mean
        print(f"\n  Summary ({len(cos_pred_reals)} edits):")
        print(f"    cos(real_action_pred, after):   mean={real_mean:.4f}")
        print(f"    cos(random_action_pred, after): mean={rand_mean:.4f}")
        print(f"    cos(before, after):             mean={np.mean(cos_before_afters):.4f}")
        print(f"    LIFT (real - random):            {lift:+.4f} {'<<< action signal' if lift > 0.01 else '(weak/no signal)'}")
        print(f"    L2(predicted, actual_after):     mean={np.mean(l2_dists):.2f}")

    return {
        "n_edits": len(cos_pred_reals),
        "cos_real_mean": float(np.mean(cos_pred_reals)) if cos_pred_reals else None,
        "cos_random_mean": float(np.mean(cos_random_baselines)) if cos_random_baselines else None,
        "lift": float(np.mean(cos_pred_reals) - np.mean(cos_random_baselines)) if cos_pred_reals else None,
        "l2_mean": float(np.mean(l2_dists)) if l2_dists else None,
    }


def assess_retrieval(backend, ast_tok, files: list[Path], repo: Path) -> dict[str, Any]:
    """Pick query files, rank others by latent sim, check if same-module files rank high."""
    print("\n━━━ 3. RETRIEVAL ━━━")

    max_len = min(128, backend.config["max_seq_len"])
    embeddings = []
    names = []
    dirs = []

    for f in files:
        try:
            source = f.read_text(errors="replace")
            tokens = ast_tok.ast_tokenize(source, max_len=max_len)
            tokens = np.array(tokens, dtype=np.int64).reshape(1, -1)
            z = backend.encode_state(tokens)
            embeddings.append(z.flatten())
            names.append(str(f.relative_to(repo)))
            dirs.append(str(f.relative_to(repo).parent))
        except Exception:
            continue

    if len(embeddings) < 10:
        print("  Too few files, skipping")
        return {"n_queries": 0}

    E = np.stack(embeddings)
    norms = np.linalg.norm(E, axis=1, keepdims=True) + 1e-8
    E_norm = E / norms

    # Pick 5 query files from directories with multiple files
    from collections import Counter
    dir_counts = Counter(dirs)
    multi_dirs = {d for d, c in dir_counts.items() if c >= 2}

    queries = []
    for i, (name, d) in enumerate(zip(names, dirs)):
        if d in multi_dirs and len(queries) < 5:
            queries.append(i)

    if not queries:
        print("  No multi-file directories, skipping")
        return {"n_queries": 0}

    hits_at_3 = 0
    hits_at_5 = 0
    total = 0

    for qi in queries:
        sims = (E_norm @ E_norm[qi]).flatten()
        sims[qi] = -999  # exclude self
        ranked = np.argsort(-sims)

        query_dir = dirs[qi]
        top_5_dirs = [dirs[r] for r in ranked[:5]]
        top_3_dirs = top_5_dirs[:3]

        hit3 = query_dir in top_3_dirs
        hit5 = query_dir in top_5_dirs
        hits_at_3 += hit3
        hits_at_5 += hit5
        total += 1

        marker3 = "+" if hit3 else "-"
        print(f"  Query: {names[qi][:50]}")
        print(f"    Top-3 [{marker3}]: {', '.join(names[r][:35] for r in ranked[:3])}")

    if total:
        print(f"\n  Same-dir hit@3: {hits_at_3}/{total} ({100*hits_at_3/total:.0f}%)")
        print(f"  Same-dir hit@5: {hits_at_5}/{total} ({100*hits_at_5/total:.0f}%)")

    return {
        "n_queries": total,
        "hit_at_3": hits_at_3 / total if total else 0,
        "hit_at_5": hits_at_5 / total if total else 0,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="Assess CodeWM on real Python codebases")
    p.add_argument("--ckpt", required=True, help="Path to .pt checkpoint")
    p.add_argument("--repo", default=".", help="Path to Python repo (default: cwd)")
    p.add_argument("--src", default=None, help="Path to architectures/ dir")
    p.add_argument("--max-files", type=int, default=40)
    p.add_argument("--device", default="cpu")
    args = p.parse_args()

    repo = Path(args.repo).resolve()
    taps_root = Path(args.src or (Path.home() / ".crucible-hub" / "taps" / "crucible-community-tap" / "architectures")).resolve()

    print("=" * 70)
    print("CodeWM Code Intelligence Assessment (EXPERIMENTAL)")
    print("=" * 70)
    print(f"  repo: {repo}")
    print(f"  ckpt: {args.ckpt}")

    # Load backend
    from eval.codewm.pytorch_backend import PyTorchCodeWMBackend
    backend = PyTorchCodeWMBackend(
        ckpt_path=args.ckpt,
        src_path=str(taps_root),
        device=args.device,
    )

    # Load tokenizers + ast_diff
    ast_tok, diff_tok, ast_diff_mod = _load_taps_modules(taps_root.parent)

    # Collect files
    files = _collect_python_files(repo, max_files=args.max_files)
    print(f"  Python files found: {len(files)}")

    t0 = time.perf_counter()

    # Run assessments
    sim_results = assess_similarity(backend, ast_tok, files, repo)

    # Small edits (baseline)
    diffs = _git_recent_diffs(repo, n=15)
    edit_results = assess_edit_prediction(backend, ast_tok, ast_diff_mod, diffs)

    # Large edits (structural changes where predictor should shine)
    print("\n  --- Re-running with large edits (min 20 changed lines) ---")
    big_diffs = _git_recent_diffs(repo, n=15, min_diff_lines=20)
    big_edit_results = assess_edit_prediction(backend, ast_tok, ast_diff_mod, big_diffs)

    retrieval_results = assess_retrieval(backend, ast_tok, files, repo)

    elapsed = time.perf_counter() - t0

    print("\n" + "=" * 70)
    print(f"  Total time: {elapsed:.1f}s")
    print("=" * 70)


if __name__ == "__main__":
    main()
