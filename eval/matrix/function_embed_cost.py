"""The CPU cost of function-unit CodeRankEmbed embeddings (2026-10-19).

The frozen rule is packages/code-intel/evals/designs/2026-10-19-cpu-fn-embed-cost.json.
Run on a Linux host. CODE is a checkout of this repository.

  python emb_cost.py prepare WORK CODE          clone, discover, parse, tokenize, sample
  python emb_cost.py encode WORK CODE CONFIG    one config, pinned to its thread count; CONFIG like fp32-512-8
  python emb_cost.py full WORK CODE REPO CONFIG one full index, to check the estimates
  python emb_cost.py summary WORK               merge the results and apply the rule
"""
import json
import random
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path

MODEL = "nomic-ai/CodeRankEmbed"
REVISION = "3c4b60807d71f79b43f3c4363786d9493691f8b1"
PREFIX = "Represent this query for searching relevant code: "
SAMPLE, BATCH = 1000, 16
FREEZE = Path(__file__).resolve().parents[2] / "packages/code-intel/evals/designs/2026-10-19-cpu-fn-embed-cost.json"
REPOS = json.loads(FREEZE.read_text())["repos"]


def log(text):
    print(f"{time.strftime('%H:%M:%S')} {text}", flush=True)


def units_of(args):
    path, rel, is_test = args
    from attocode_intel._internal.integrations.context.codebase_ast import parse_file
    try:
        source = Path(path).read_text(errors="replace")
        ast = parse_file(path, source)
    except Exception:
        return []
    lines = source.splitlines()
    defs = list(ast.functions) + [m for c in ast.classes for m in c.methods]
    return [{"file": rel, "name": d.name, "test": is_test,
             "text": f"{rel}\n" + "\n".join(lines[d.start_line - 1:d.end_line])} for d in defs]


def prepare(work, code):
    from multiprocessing import Pool

    from attocode_intel._internal.integrations.context.codebase_context import (
        CodebaseContextManager,
    )
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION)
    for name, (repo, sha) in REPOS.items():
        src = work / "src" / name
        if not (src / ".git").exists():
            src.mkdir(parents=True, exist_ok=True)
            for cmd in (["init", "-q"], ["remote", "add", "origin", f"https://github.com/{repo}"],
                        ["fetch", "-q", "--depth", "1", "origin", sha], ["checkout", "-q", "--detach", "FETCH_HEAD"]):
                subprocess.run(["git", "-C", str(src), *cmd], check=True)
        head = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        assert head == sha, (name, head)
        t0 = time.time()
        ctx = CodebaseContextManager(root_dir=str(src))
        files = [f for f in ctx.discover_files() if f.language]
        t1 = time.time()
        with Pool(16) as pool:
            units = [u for part in pool.map(units_of, [(f.path, f.relative_path, f.is_test) for f in files],
                                            chunksize=16) for u in part]
        t2 = time.time()
        lengths = []
        for i in range(0, len(units), 2000):
            lengths += [len(x) for x in tokenizer([u["text"] for u in units[i:i + 2000]])["input_ids"]]
        sample = sorted(random.Random(0).sample(range(len(units)), min(SAMPLE, len(units))))
        cut = sorted(lengths)
        info = {"repo": repo, "commit": sha, "files": len(files), "units": len(units),
                "discovered": ctx.discovered_file_count, "discovery_truncated": ctx.discovery_truncated,
                "test_units": sum(u["test"] for u in units), "discover_s": round(t1 - t0, 2),
                "parse_s": round(t2 - t1, 2),
                "tokens": {"p50": cut[len(cut) // 2], "p90": cut[len(cut) * 9 // 10], "max": cut[-1],
                           "over_512": sum(n > 512 for n in lengths), "over_1024": sum(n > 1024 for n in lengths),
                           "sum_capped_512": sum(min(n, 512) for n in lengths),
                           "sum_capped_1024": sum(min(n, 1024) for n in lengths)},
                "sample": sample}
        (work / "units").mkdir(exist_ok=True)
        (work / "units" / f"{name}.json").write_text(json.dumps(info))
        (work / "units" / f"{name}.texts.json").write_text(json.dumps([u["text"] for u in units]))
        (work / "units" / f"{name}.sample.json").write_text(json.dumps([units[i]["text"] for i in sample]))
        log(f"{name}: {len(files)} files, {len(units)} units, tokens p50 {info['tokens']['p50']}, "
            f"discover {info['discover_s']} s, parse {info['parse_s']} s")


def load(config):
    import torch
    from sentence_transformers import SentenceTransformer
    weights, seq, threads = config.split("-")
    torch.set_num_threads(int(threads))
    t0 = time.time()
    model = SentenceTransformer(MODEL, revision=REVISION, trust_remote_code=True, device="cpu")
    model.max_seq_length = int(seq)
    if weights == "int8":
        model[0].auto_model = torch.ao.quantization.quantize_dynamic(
            model[0].auto_model, {torch.nn.Linear}, dtype=torch.qint8)
    return model, round(time.time() - t0, 2)


def host():
    import os
    cpuinfo = Path("/proc/cpuinfo").read_text().splitlines()
    cpu = next((line.split(":", 1)[1].strip() for line in cpuinfo if line.startswith("model name")), "")
    cpu_max = Path("/sys/fs/cgroup/cpu.max")
    return {"cpu": cpu, "nproc": os.cpu_count(), "affinity": sorted(os.sched_getaffinity(0)),
            "cpu_max": cpu_max.read_text().strip() if cpu_max.exists() else None}


def rss_mib():
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)  # Linux: KiB


def encode(work, code, config):
    import numpy as np
    import yaml
    model, load_s = load(config)
    out = {"config": config, "load_s": load_s, "rss_after_load_mib": rss_mib(), "host": host(), "repos": {}}
    model.encode(["def warm(): pass"] * BATCH, batch_size=BATCH)
    (work / "vectors").mkdir(exist_ok=True)
    for name in REPOS:
        info = json.loads((work / "units" / f"{name}.json").read_text())
        sample = json.loads((work / "units" / f"{name}.sample.json").read_text())
        t0 = time.time()
        vec = model.encode(sample, batch_size=BATCH)
        sec = time.time() - t0
        np.save(work / "vectors" / f"{config}-{name}.npy", vec.astype("float32"))
        out["repos"][name] = {"sample": len(sample), "seconds": round(sec, 2),
                              "units_per_s": round(len(sample) / sec, 2),
                              "estimate_full_min": round(sec / len(sample) * info["units"] / 60, 2)}
        log(f"{config} {name}: {len(sample)} units in {sec:.1f} s, estimate {out['repos'][name]['estimate_full_min']} min")
    packs = yaml.safe_load((Path(code) / "eval/quality/workflows.yaml").read_text())["repositories"]
    queries = [q["query"] for p in packs for q in p.get("queries", [])][:50]
    for q in queries[:5]:
        model.encode([PREFIX + q])
    times = []
    for q in queries:
        t0 = time.perf_counter()
        model.encode([PREFIX + q])
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    out["query_ms"] = {"n": len(times), "p50": round(statistics.median(times), 1),
                       "p95": round(times[int(len(times) * 0.95) - 1], 1), "max": round(times[-1], 1)}
    out["peak_rss_mib"] = rss_mib()
    (work / "results").mkdir(exist_ok=True)
    (work / "results" / f"{config}.json").write_text(json.dumps(out, indent=1))
    log(f"{config}: query p50 {out['query_ms']['p50']} p95 {out['query_ms']['p95']} ms, peak RSS {out['peak_rss_mib']} MiB")


def full(work, code, name, config):
    model, load_s = load(config)
    texts = json.loads((work / "units" / f"{name}.texts.json").read_text())
    t0 = time.time()
    model.encode(texts, batch_size=BATCH)
    sec = time.time() - t0
    out = {"repo": name, "config": config, "units": len(texts), "seconds": round(sec, 1),
           "minutes": round(sec / 60, 2), "units_per_s": round(len(texts) / sec, 2), "peak_rss_mib": rss_mib()}
    (work / "results" / f"full-{name}-{config}.json").write_text(json.dumps(out, indent=1))
    log(f"full {name} {config}: {len(texts)} units in {sec / 60:.2f} min, peak RSS {out['peak_rss_mib']} MiB")


def summary(work):
    import numpy as np
    freeze = json.loads(FREEZE.read_text())
    units = {n: json.loads((work / "units" / f"{n}.json").read_text()) for n in REPOS}
    for u in units.values():
        u.pop("sample")
    results = {c: json.loads((work / "results" / f"{c}.json").read_text())
               for c in freeze["configs"] if (work / "results" / f"{c}.json").exists()}
    order = sorted(REPOS, key=lambda n: units[n]["units"])
    median, largest = order[len(order) // 2], order[-1]
    cosine = {}
    for n in REPOS:
        a, b = (work / "vectors" / f"fp32-512-8-{n}.npy"), (work / "vectors" / f"int8-512-8-{n}.npy")
        if a.exists() and b.exists():
            x, y = np.load(a), np.load(b)
            c = (x * y).sum(1) / (np.linalg.norm(x, axis=1) * np.linalg.norm(y, axis=1))
            cosine[n] = {"mean": round(float(c.mean()), 4), "p01": round(float(np.percentile(c, 1)), 4)}
    cos_mean = statistics.mean(v["mean"] for v in cosine.values()) if cosine else None
    checks = {}
    for c, r in results.items():
        if not c.endswith("-8"):
            continue
        checks[c] = {"query_p95_ms": r["query_ms"]["p95"], "query_ok": r["query_ms"]["p95"] <= 150,
                     "median_repo": median, "median_min": r["repos"][median]["estimate_full_min"],
                     "median_ok": r["repos"][median]["estimate_full_min"] <= 10,
                     "largest_repo": largest, "largest_min": r["repos"][largest]["estimate_full_min"],
                     "largest_ok": r["repos"][largest]["estimate_full_min"] <= 60,
                     "peak_rss_mib": r["peak_rss_mib"], "rss_ok": r["peak_rss_mib"] <= 2048}
        if c.startswith("int8"):
            checks[c]["cosine_mean"] = cos_mean
            checks[c]["cosine_ok"] = cos_mean is not None and cos_mean >= 0.99
        checks[c]["pass"] = all(v for k, v in checks[c].items() if k.endswith("_ok"))
    full_check = None
    fpath = work / "results" / "full-cli-fp32-512-8.json"
    if fpath.exists() and "fp32-512-8" in results:
        f = json.loads(fpath.read_text())
        est = results["fp32-512-8"]["repos"]["cli"]["estimate_full_min"]
        full_check = {"estimate_min": est, "actual_min": f["minutes"], "ratio": round(f["minutes"] / est, 3),
                      "within_20pct": abs(f["minutes"] / est - 1) <= 0.2, "peak_rss_mib": f["peak_rss_mib"]}
    out = {"units": units, "results": results, "int8_cosine": cosine, "checks": checks,
           "estimate_check": full_check, "decision": "pass" if any(v["pass"] for v in checks.values()) else "fail"}
    (work / "summary.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({"checks": checks, "estimate_check": full_check, "int8_cosine": cosine,
                      "decision": out["decision"]}, indent=1))


if __name__ == "__main__":
    step, work = sys.argv[1], Path(sys.argv[2])
    if step in ("encode", "full"):
        # Pin before torch loads: the first N allowed vCPUs, and the same thread count for OpenMP and MKL.
        import os
        threads = int(sys.argv[-1].split("-")[-1])
        os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:threads])
        os.environ["OMP_NUM_THREADS"] = os.environ["MKL_NUM_THREADS"] = str(threads)
    if len(sys.argv) > 3:
        sys.path[:0] = [sys.argv[3], f"{sys.argv[3]}/packages/code-intel/src"]
    {"prepare": lambda: prepare(work, sys.argv[3]),
     "encode": lambda: encode(work, sys.argv[3], sys.argv[4]),
     "full": lambda: full(work, sys.argv[3], sys.argv[4], sys.argv[5]),
     "summary": lambda: summary(work)}[step]()
