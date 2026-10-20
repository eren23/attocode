# CPU cost of function-unit embeddings (2026-10-19)

**Status: fail. CodeRankEmbed over function units is too slow on 8 CPU
threads for an opt-in product mode. The query time passes (p95 52.9 ms).
The index time fails: 21.6 minutes for the median repository (limit 10)
and 293 minutes for the largest (limit 60). Peak memory is 2,107 MiB
(limit 2,048). A naive int8 model is only 1.25 times faster, and it
changes the vectors (mean cosine 0.81 to fp32). One full index confirmed
the estimates within 5 percent.**

## The question

On Loc-Bench 560, `fn-dense` (CodeRankEmbed over function units) gave
0.739 Acc@5, against 0.566 for `product`
([2026-10-18](2026-10-18-locbench-remeasure.md)). The function unit gives
+0.055 of that gain ([2026-10-19](2026-10-19-function-bm25.md)). That run
used a GPU. This test asks whether a CPU can build and query the same
index as an opt-in product mode. It measures cost only, not quality.

## What we ran

- **Code.** `main` at `94471b6`. The script is
  `eval/matrix/function_embed_cost.py`.
- **Model.** `nomic-ai/CodeRankEmbed` at revision `3c4b6080`, the revision
  of `eval.matrix.dense`.
- **Units.** Product discovery and product `parse_file`: every top-level
  function and every class method, in all parsed languages. The units include
  test files. The text of a unit is its relative path, a newline and its
  source lines.
- **Configs.** Weights, maximum tokens and CPU threads: `fp32-512-8`,
  `int8-512-8`, `fp32-1024-8` and `fp32-512-4`. Each config runs in its own
  process. The process pins itself to that many vCPUs before torch loads.
  int8 uses `torch.ao.quantization.quantize_dynamic` on the linear layers.
- **Measure.** 1,000 random units of each repository (all units if fewer),
  batch 16. The seconds for each unit times the unit count give the full
  index time. Query time is 50 workflow-pack queries, one at a time, after
  5 warm-up calls. Memory is the peak RSS of the process.
- **Computer.** One RunPod pod: AMD EPYC 7282 (Zen 2, AVX2), 64 visible
  vCPUs, a cgroup quota of 13.6 CPUs. The pod had a GPU (RTX PRO 4500 SE),
  but the test did not use it. torch 2.8.0, sentence-transformers 3.4.1.

| Repository | Commit | Files | Units | Test units | Token p50 | Token p90 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| express | `6c4249fe` | 158 | 175 | 30 | 73 | 205 |
| fastapi | `11614be9` | 2,640 | 4,583 | 3,491 | 91 | 264 |
| cli | `6e49747f` | 904 | 4,893 | 1,659 | 180 | 817 |
| pandas | `0039f168` | 1,658 | 31,056 | 20,979 | 148 | 415 |
| cockroach | `53aadff3` | 8,462 | 80,319 | 7,727 | 103 | 576 |

By unit count, `cli` is the median repository and `cockroach` is the
largest.

## Frozen rule

We wrote the rule before the pod started
([design](../designs/2026-10-19-cpu-fn-embed-cost.json)). The test passes
if at least one 8-thread config meets all of these limits:

1. Query p95 ≤ 150 ms.
2. Estimated full index ≤ 10 minutes for the median repository.
3. Estimated full index ≤ 60 minutes for the largest repository.
4. Peak RSS ≤ 2 GiB.
5. For int8: a mean cosine to fp32 of at least 0.99.

One full index of `cli` with `fp32-512-8` must fall within 20 percent of
its estimate. Otherwise every estimate is unreliable.

## Results

| Config | Query p95 | cli | cockroach | Peak RSS | int8 cosine | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `fp32-512-8` | 52.9 ms | 21.56 min | 293.22 min | 2,107 MiB | | no |
| `int8-512-8` | 23.1 ms | 17.10 min | 225.19 min | 2,205 MiB | 0.810 | no |
| `fp32-1024-8` | 63.3 ms | 31.58 min | 466.95 min | 3,274 MiB | | no |

Only the query limit passes, in all three configs. Estimated full index
times for the other repositories with
`fp32-512-8`: express 0.38 minutes, fastapi 9.32, pandas 111.98.

- **Estimate check.** The full `cli` index took 20.57 minutes for 4,893
  units, against an estimate of 21.56 minutes (ratio 0.954). The estimates
  are reliable.
- **Throughput.** `fp32-512-8` encodes 3.8 to 8.2 units per second. Go
  units in `cli` are the longest, and they are the slowest.
- **Memory.** The model alone needs 1,883 MiB after it loads, before it
  encodes a unit.
- **int8.** Per repository, the mean cosine to fp32 is 0.78 to 0.83. This
  quantization method changes the vectors too much to keep the quality of
  the fp32 model.
- **Gap.** To meet the limits, `fp32-512-8` must be 2.2 times faster for
  `cli` and 4.9 times faster for `cockroach`.

## Changes during the run

The rule did not change. The run order did:

1. The planned order was the four configs, then the full `cli` check. The
   pod had a time limit, so the check moved forward.
2. After `int8-512-8` finished (20:51:05Z), the operator stopped
   `fp32-1024-8` and started the full check. `fp32-1024-8` then ran again
   from the start.
3. `fp32-512-4` stopped at the time limit after 3 of 5 repositories. Its
   partial `cli` estimate is 37.2 minutes. The rule uses only 8-thread
   configs, so this partial result does not change the decision.

The script reads only the cgroup v2 quota. The pod used cgroup v1, so the
JSON records the quota as null. We read the 13.6-CPU quota by hand.

## Limits

- **One older CPU.** Zen 2 is from 2019 and has no AVX-512 VNNI or AMX.
  A newer server CPU can be faster. Apple Silicon with MPS was not
  measured.
- **One int8 method.** Dynamic quantization of the linear layers only.
  ONNX Runtime or OpenVINO int8 can keep more quality. They were not
  tested.
- **No shorter units.** A cap of 256 tokens was not tested.
- **No quality.** The test measures cost only.
- **express.** The JavaScript parser makes no unit from a function that
  the code assigns to a property (`res.send = function ...`). Thus express
  has only 175 units. It is the smallest repository, so this does not
  change the median or the largest.

## What this means

A full CPU index of function units is not a product option on this class
of hardware. The query side is cheap, but the index side is 2 to 5 times
too slow. Encoding only a short candidate list at query time is not cheap
either: at 4 to 8 units per second, 24 candidates take about 3 to 6
seconds. This estimate comes from the throughput above, not from a
measurement. A useful function-unit embedding needs a GPU or a remote
service.

## Reproduce

On a Linux x86 host with this repository at `94471b6` and the model
installed:

1. Run `python eval/matrix/function_embed_cost.py prepare WORK CODE`.
2. For each config, run
   `python eval/matrix/function_embed_cost.py encode WORK CODE CONFIG`.
3. Run `python eval/matrix/function_embed_cost.py full WORK CODE cli fp32-512-8`.
4. Run `python eval/matrix/function_embed_cost.py summary WORK`.

## Spend

The pod ran 85.8 minutes at $0.50 an hour, about $0.72. This is an
estimate. We did not check the invoice. We destroyed the pod at 21:46Z,
and the fleet then had no nodes.

## Artifacts

- [Design](../designs/2026-10-19-cpu-fn-embed-cost.json): the frozen rule.
- [Summary](2026-10-19-cpu-fn-embed-cost.json): the units, every config,
  the checks, the estimate check, the int8 cosines, the run order, the
  spend and the SHA-256 of the frozen script.
- The logs and the per-config result files stay private.
