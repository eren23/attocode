# Codex repair diagnostic

Authorized scope: two excluded wiring attempts, then four exploratory repairs,
using the first two tasks in the prepared R7 manifest. No replacements or retries
after model outcomes. Claude R7 remains frozen and unstarted until its reset.

Study: `~/Documents/AI/attocode-evals/matrix/studies/codex-repair-smoke`.
Frozen id: `af58925e1df670347a6d7a10244517acbb116c223709a9a4309e14f1fd4359b5`.

- Client: Codex CLI 0.162.1, ChatGPT subscription login, explicitly requested
  `gpt-6.1-sol`, high reasoning, default service tier.
- Tasks: `astropy__astropy-6938`, `mwaskom__seaborn-3010`. These development
  tasks are already known to the operator; they are not held out.
- Arms: native tools; native tools plus optional local lean MCP. Order:
  Astropy native/lean, Seaborn lean/native. One attempt per task and arm.
- Six model attempts maximum, each limited to 600 seconds. Execute one at a time.
  Each work session ends within 50 minutes; an unfinished attempt is preserved.
- Check account and included quota before each request. Require
  `ordinaryUsageAllowed=true` and every reported usage window below 20% used.
  Compare credit balances after each attempt and stop on a decrease or missing
  balance. Automatic reload was visibly off; existing credits were available.
  This is an observed guard, not a provider-enforced prohibition on credit use.
- Preserve raw CLI events, submitted patches, timings, token usage and grading.
  Codex does not supply a dollar estimate; do not invent one.

Both wiring attempts edit a disposable `VALUE=1` fixture to `VALUE=2` and run an
assertion in the pinned runtime. Lean wiring also requires an answered
`inspect_symbol` call. A model-free MCP check verifies the seven advertised lean
tools. Both wiring traces require operator review before repairs can start.

The instruction adaptation is explicit: `project_doc_max_bytes=0` suppressed
project guidance but still loaded the real global AGENTS file. A private
disposable `CODEX_HOME` with a symlink to the existing login passed the model-free
instruction-source check with an empty list. No personal file was changed or
credential copied. Personal skills, plugins, apps, hooks, memory, goals and agent
delegation are disabled per invocation. Optional lean routing comes through an
explicit developer instruction rather than installed project AGENTS.

Each task uses the prepared public source and a pinned offline Docker image.
All eight image/mounted-source base/gold controls passed independently. The
strict frozen grader restores official test paths and requires every fail-to-pass
and pass-to-pass case plus a successful exit. Grade patches in a separate fresh
container. Read all command and file-change traces before accepting a result;
the host shell and Docker socket do not provide OS isolation from private inputs.

Report wiring, resolution, adoption, tokens and elapsed time descriptively.
Four repairs cannot establish a quality improvement or support a model comparison.
No R7 statistical gate, ranking default, release or daily tool-list change follows
from this diagnostic alone.
