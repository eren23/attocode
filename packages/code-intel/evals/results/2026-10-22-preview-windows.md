# Contiguous preview trial — incomplete

The single [online attempt](https://github.com/eren23/attocode/actions/runs/39836664440)
stopped on an operator decoding error. There is **no search-quality verdict**,
and no preview or ranking change is enabled. The frozen trial is closed without
a retry, retuning or replacement questions.

The evaluation-only candidate keeps retrieval and result order unchanged. It
replaces a preview only when another contiguous whole-line window, within the
same character limit, contains a strict superset of its positive query terms.
Twelve implementer-authored questions were frozen before retrieval: six each
from pinned pandas and ripgrep, including behavioral and exact-name controls.
Prior repository exposure and prior labeling of ripgrep's distinct `quiet_stats`
test in the same JSON file were disclosed; these are not blind judgments.

Runner checks first produce exactly two expected assertion failures among 13
baseline controls, then **13 passing candidate controls**. The pandas comparison
records 13 baseline pages for the first three questions. It then fails when
`source_spans` uses strict UTF-8 decoding on a returned file containing byte
`0xd0`. No candidate page or ripgrep comparison runs. The failing response was
not checkpointed before admission, so its exact path and text are unavailable.
Neither the file's type nor a product defect can be inferred from that exception.

The run takes 28.865 seconds. Sampled aggregate controller/descendant RSS peaks at
276,770,816 bytes and owned disk at 239,362,048 bytes, within the frozen 2 GiB limits;
no budget violation is recorded. Owned scratch removal and operator/source
identities verify. The whole frozen question batch is conservatively consumed
for future freshness. A future redesigned validator must follow the product's
decoding policy and checkpoint raw responses before validating them.

The [machine report](2026-10-22-preview-windows.json) binds the exact runner
artifact and [archive](2026-10-22-preview-windows.tar.gz). The archive retains
the frozen operator, candidate, tests, questions, raw artifact and a standard
library replay that verifies hashes and incomplete-outcome arithmetic without
running product code or accessing the network. It does not reconstruct the
missing failing page or establish a relevance gain. All runtime validation ran
on GitHub Actions; none ran on the Mac.
