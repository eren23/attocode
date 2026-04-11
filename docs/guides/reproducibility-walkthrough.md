# Reproducibility Walkthrough

This guide walks you through the Code-Intel reproducibility surface end-to-end
on a real (but small) fixture repo. You'll mint a retrieval pin, capture a
snapshot, introduce a change, verify that the pin drifts, restore the
snapshot, and confirm reproducibility. ~10 minutes.

Every step shows the **exact tool call** you'd issue from an MCP client
(Claude Code, Cursor, Windsurf, etc.), the **expected output** shape, and
what to assert to know the step worked.

If any step fails, the feature is broken — skip to the
[Troubleshooting](#troubleshooting) section.

---

## Prerequisites

- `uv` installed (`brew install uv` or `pipx install uv`).
- You've cloned `attocode/first-principles-agent` and run `uv sync`.
- An MCP client you can drive manually — Claude Code, Cursor, or any tool
  that can invoke `mcp__attocode-code-intel__*` functions.

The repo already ships a `.cursor/mcp.json` that auto-loads
`attocode-code-intel --local-only` when Cursor or Claude Code opens the
workspace, so there's nothing to configure. Just open the repo.

For users running this against a different project, point your MCP client
at `attocode-code-intel --project /path/to/your/repo --local-only`.

## Setup

Open the fixture repo in a fresh MCP session:

```bash
cd /Users/eren/Documents/AI/first-principles-agent
uv sync
# In a second terminal or via your MCP client:
uv run attocode-code-intel --project tests/fixtures/sample_project --local-only
```

Then call `bootstrap` once to warm the indexes:

```json
// tool: mcp__attocode-code-intel__bootstrap
{}
```

Expected output: one-paragraph summary of the fixture repo (file count,
language mix, entry points). The exact numbers don't matter — you just
need it to succeed.

---

## Step 1 — Mint a pin against the current state

```json
// tool: mcp__attocode-code-intel__pin_current
{
  "ttl_seconds": 0
}
```

`ttl_seconds: 0` means "never expire". You can use `86400` (24h) for
agent-session scoped pins.

**Expected output shape:**

```
Pinned: pin_1f9a2b3c4d5e6f708192
manifest_hash: 1f9a2b3c4d5e6f708192a3b4c5d6e7f809102132435465768796a7b8c9d0e1f2
expires_in: never
stores:
  - adrs: sha256:…
  - embeddings: sha256:…
  - frecency: sha256:…
  - kw_index: sha256:…
  - learnings: sha256:…
  - query_history: sha256:…
  - symbols: sha256:…
  - trigrams: sha256:…
```

**Record the `pin_id`** — you'll use it in steps 4, 8, and 10. The exact
hex will differ for your machine; that's fine.

**Assertion:** the response starts with `Pinned: pin_` followed by 20
hex chars, and lists at least 8 store entries. If you see fewer stores,
some stores aren't present on disk yet (expected on a fresh bootstrap —
the cache manifest uses "absent" as a stable sentinel).

---

## Step 2 — Run a search and observe the auto-stamped pin

```json
// tool: mcp__attocode-code-intel__semantic_search
{
  "query": "main entry point",
  "top_k": 5
}
```

**Expected output shape:**

```
<results body — ranked file:line hits with snippets>

---
index_pin: pin_1f9a2b3c4d5e6f708192
manifest_hash: 1f9a2b3c4d5e6f708192a3b4c5d6e7f809102132435465768796a7b8c9d0e1f2
```

**Assertion:** the `index_pin` and `manifest_hash` in the footer match
what `pin_current` returned in Step 1 — **byte for byte**. That's the
whole determinism contract: minting a pin, then running a search on
unchanged state, produces identical identifiers.

If they don't match, a background indexer ran between Step 1 and Step 2
(possible if the fixture repo has file watchers on something). You can
retry — pin_current is idempotent under stable state.

---

## Step 3 — Create a baseline snapshot

```json
// tool: mcp__attocode-code-intel__snapshot_create
{
  "name": "walkthrough-baseline",
  "include": ""
}
```

Empty `include` means "capture every component". You can narrow to
`"symbols,embeddings,trigrams"` if you only care about the index layer.

**Expected output shape:**

```
snapshot_create: /path/to/tests/fixtures/sample_project/.attocode/snapshots/walkthrough-baseline.atsnap.tar.gz
  components: 10
  total_size_uncompressed: 45.2 MB
  archive_size: 12.8 MB
```

**Assertion:** the archive exists on disk. In a shell:

```bash
ls -la tests/fixtures/sample_project/.attocode/snapshots/walkthrough-baseline.atsnap.tar.gz
```

You should see a single file with non-zero size.

**Bonus: peek at the manifest** without extracting:

```bash
tar -xOzf tests/fixtures/sample_project/.attocode/snapshots/walkthrough-baseline.atsnap.tar.gz manifest.json | head -20
```

The `project_name` field should be the basename (`sample_project`), not
an absolute path — that's the round-2 portability fix.

---

## Step 4 — List and diff snapshots

```json
// tool: mcp__attocode-code-intel__snapshot_list
{}
```

**Expected output:** one row for `walkthrough-baseline.atsnap.tar.gz` with
size and mtime. Only one snapshot exists right now.

```json
// tool: mcp__attocode-code-intel__snapshot_diff
{
  "a": "walkthrough-baseline",
  "b": "walkthrough-baseline"
}
```

**Expected output:** "no changes" — a snapshot compared to itself has no
drift. This confirms the diff tool works before we introduce real drift
in Step 6.

---

## Step 5 — Dry-run clear_embeddings

```json
// tool: mcp__attocode-code-intel__clear_embeddings
{
  "confirm": false
}
```

**Expected output shape:**

```
clear_embeddings (dry run): would wipe 1,247 rows (32.8 MB)
  path: /.../.attocode/vectors/embeddings.db
  model breakdown: bge=1247
Pass confirm=True to actually delete.
```

**Assertion:** the response mentions "dry run" and does NOT say "deleted".
Check the file still exists at its original size:

```bash
ls -la tests/fixtures/sample_project/.attocode/vectors/embeddings.db
```

This step is purely a safety demonstration — it proves the `confirm=False`
default pattern protects you from accidental deletion. Do **not** pass
`confirm=True` yet; we need the embeddings intact for Step 8.

---

## Step 6 — Introduce a change to the fixture repo

In your editor, append a line to any source file in the fixture:

```bash
echo "# walkthrough dogfood marker" >> tests/fixtures/sample_project/main.py
```

Wait 2–3 seconds for the file watcher to notice. Then call `bootstrap`
again or let the watcher re-index:

```json
// tool: mcp__attocode-code-intel__bootstrap
{}
```

This triggers a reindex of `main.py`, which updates `symbols.db` (new row
checksum), `kw_index.db` (new doc terms), and possibly `embeddings.db` (if
embeddings are cached by content hash).

---

## Step 7 — Re-run the same semantic_search and observe a new pin

```json
// tool: mcp__attocode-code-intel__semantic_search
{
  "query": "main entry point",
  "top_k": 5
}
```

**Expected output:** same ranked results (probably), but the footer
now shows a **different** `pin_id` and `manifest_hash`. The stores that
were touched in Step 6 have different hashes; that propagates into the
manifest hash and therefore into the derived pin id.

**Assertion:** the new pin_id is NOT equal to the one from Step 1.

---

## Step 8 — Verify drift against the Step 1 pin

Use the `pin_id` you recorded in Step 1:

```json
// tool: mcp__attocode-code-intel__verify_pin
{
  "pin_id": "pin_1f9a2b3c4d5e6f708192"  // ← your pin_id from Step 1
}
```

**Expected output shape:**

```
Pin pin_1f9a2b3c4d5e6f708192: DRIFT in 3 store(s):
  - symbols: pinned=a1b2c3d4e5f60718… current=f1e2d3c4b5a69708…
  - kw_index: pinned=7a8b9c0d1e2f3040… current=4f5e6d7c8b9a0102…
  - trigrams: pinned=9e8d7c6b5a493827… current=1a2b3c4d5e6f7080…
```

**Assertion:** the drift report is non-empty and lists the exact stores
that were rewritten by the edit in Step 6. Stores that weren't touched
(e.g. `adrs`, `query_history`) should NOT appear in the drift list.

**This is the core reproducibility contract in action:** the pin
remembers what state the original query was answered against, and
`verify_pin` tells you precisely which stores have changed since then.

---

## Step 9 — Restore the baseline snapshot

```json
// tool: mcp__attocode-code-intel__snapshot_restore
{
  "name": "walkthrough-baseline",
  "confirm": true
}
```

`confirm=true` is required for destructive ops. Without it, you'd see a
dry-run preview instead. Under the hood, the tool does an atomic
staging-dir-plus-rename dance — if anything fails, the live `.attocode/`
is never touched.

**Expected output shape:**

```
snapshot_restore: walkthrough-baseline
  restored 10 components (45.2 MB)
  staging dir cleaned up
  live caches reloaded
```

**Assertion:** the response says "restored" (not "would restore"). The
SQLite stores under `.attocode/` now match the Step 3 manifest.

---

## Step 10 — Re-verify the Step 1 pin after restore

```json
// tool: mcp__attocode-code-intel__verify_pin
{
  "pin_id": "pin_1f9a2b3c4d5e6f708192"  // ← same Step 1 pin_id
}
```

**Expected output:**

```
Pin pin_1f9a2b3c4d5e6f708192: no drift. State is identical to the pinned snapshot.
```

**Assertion:** NO drift. Every per-store hash matches the Step 1 pin byte
for byte. **This proves end-to-end reproducibility**: a snapshot captured
at the pin time can be restored to bring the state back into pin
compliance, which means any query that was valid against the original
state will return byte-identical results after restore.

Also re-run the Step 2 search:

```json
// tool: mcp__attocode-code-intel__semantic_search
{
  "query": "main entry point",
  "top_k": 5
}
```

The `index_pin` footer should now match the Step 1 pin exactly again.
You've made a round trip: pin → snapshot → edit → drift → restore → pin
unchanged.

---

## Step 11 (optional) — Embedding rotation dry run

If you want to see the rotation state machine without actually swapping
providers:

```json
// tool: mcp__attocode-code-intel__embeddings_rotate_status
{}
```

**Expected output on a clean system:**

```
embeddings_rotate_status: no rotation active.
```

Starting a rotation requires the target provider to be installed. If you
have `nomic-embed-text` available locally:

```json
// tool: mcp__attocode-code-intel__embeddings_rotate_start
{
  "new_model": "nomic-embed-text",
  "new_version": "v1.5",
  "new_dim": 0
}
```

`new_dim: 0` tells the rotator to query the provider's own `dimension()`.
The response shows the state transition `none` → `pending` and stages a
`vectors_rotating` table. You can then call `embeddings_rotate_step` to
backfill batches, `embeddings_rotate_cutover` to swap, and
`embeddings_rotate_gc_old` to finalize. Or, for this walkthrough, abort:

```json
// tool: mcp__attocode-code-intel__embeddings_rotate_abort
{
  "confirm": true
}
```

**Assertion:** the abort response confirms the staging data was cleared
and the primary `vectors` table is untouched. Run `embeddings_status` to
verify the store is back to its pre-rotation configuration.

---

## Step 12 — Teardown

```json
// tool: mcp__attocode-code-intel__snapshot_delete
{
  "name": "walkthrough-baseline",
  "confirm": true
}
```

**Expected output:** "deleted walkthrough-baseline.atsnap.tar.gz".

```json
// tool: mcp__attocode-code-intel__pin_delete
{
  "pin_id": "pin_1f9a2b3c4d5e6f708192"  // ← Step 1 pin
}
```

**Expected output:** "Deleted pin pin_1f9a2b3c4d5e6f708192".

Also revert the edit you made in Step 6:

```bash
# Undo the appended marker line
git -C tests/fixtures/sample_project checkout main.py 2>/dev/null \
  || sed -i '' -e '/# walkthrough dogfood marker/d' tests/fixtures/sample_project/main.py
```

Stop the MCP server (`Ctrl-C` in the terminal where it's running).

---

## What you just proved

| Feature | Step | Claim verified |
|---|---|---|
| `pin_current` | 1 | Deterministic pin id derivation |
| `@pin_stamped` footer | 2, 7 | Every ranked-result tool auto-stamps state |
| `snapshot_create` | 3 | Portable tarball captures every store |
| Portable manifest | 3 | `project_name` is basename, not absolute path |
| `snapshot_list` / `snapshot_diff` | 4 | Snapshot inventory + digest comparison |
| `clear_embeddings` dry-run | 5 | `confirm=False` safety default |
| `verify_pin` drift detection | 8 | Accurate per-store drift report |
| `snapshot_restore` | 9 | Atomic restore via staging + rename |
| Round-trip reproducibility | 10 | Restore returns state to pin compliance |
| `embeddings_rotate_*` (optional) | 11 | State machine, abort path safe |

If all 10 core assertions (Steps 1–10) hold, the reproducibility surface
is working end-to-end on your machine. That's the full set of contracts
the Phase 1 → 3a work shipped.

---

## Troubleshooting

**"No pin with id pin_xxx"** on Step 8 — the pin was never persisted.
Check `embeddings_status` for a degraded vector store (the pin stamping
swallows exceptions from locked SQLite files and returns empty strings).
Most common cause: a second `attocode-code-intel` instance is running
against the same project. Kill the extras.

**Drift report shows unexpected stores** — the file watcher noticed
something else changed between steps. Fixtures with pre-existing
`.git/` can trigger frecency updates. Either use a git-less fixture or
re-run from Step 1 with the file watcher paused.

**`snapshot_restore` fails with "digest mismatch"** — the archive was
corrupted (partial copy, disk write error). The tool aborts **before**
touching `.attocode/`, so your live state is safe. Re-create the
snapshot and try again.

**`semantic_search` returns different top_k results in Step 7** —
that's OK if the edit in Step 6 added a file the search matched better.
You're testing reproducibility of the **pin**, not of the query output.
The pin footer will still differ correctly, which is what Step 8 verifies.

**Running the walkthrough in a clean CI environment** — the fixture
repo works offline. You don't need any embedding provider for steps
1–10 (keyword-mode semantic search is enough). Step 11 is the only one
that needs a real embedding provider; skip it in CI.

---

## Next steps

- Read the **[Code-Intel Reproducibility Guide](code-intel-reproducibility.md)**
  for the full tool surface reference (signatures, failure modes, when to
  use each).
- For HTTP-server-based snapshots (service mode, multi-tenant), see the
  **[Code-Intel HTTP API reference](../code-intel-http-api.md#phase-3a-reproducibility-state-tracking)**
  section.
- For CLI-based GC and verify in operator scripts, see
  **[CLI Commands](cli-commands.md)**.
