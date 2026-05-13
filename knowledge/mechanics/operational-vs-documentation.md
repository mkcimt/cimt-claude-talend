# Operational commands read live; documentation commands may cache

A guiding principle for any skill, agent, or script in this kit (and any new ones added later).

## The split

**Operational commands** — build, publish, bind, promote, deploy, undeploy, redeploy, status, review — must read their facts directly from the project's source files and from TMC at the time of execution. They never rely on cached summaries, pre-computed inventories, or values stored in a previous session.

**Documentation commands** — `/document-interface` and similar — may reference and build on cached summaries, as long as the act of producing documentation explicitly verifies live state where behaviour is at stake.

## Why the split exists

Cached information goes stale. A port number in a wiki page from three months ago may have been changed in TMC last week. A list of API endpoints in an interface doc may miss the one a colleague added on master yesterday. A summary of which joblet a job calls may not reflect the latest tRunJob edit.

For *documentation*, mild staleness is tolerable — the doc is itself a snapshot. For *operations*, mild staleness causes deploys to the wrong port, builds against the wrong artifact version, promotes that don't actually promote what the user thinks. The cost of being wrong is much higher.

## Concrete consequences

### For operational commands

- **Read `.item` files directly.** Don't lean on someone's earlier description of "what this job does".
- **Hit the TMC API** for current artifact versions, task bindings, run-configs. Don't trust local memory or a previous session's output.
- **Re-resolve every TMC ID** (artifact ID, task ID, promotion plan ID) by name + env at the start of each command, even if you saw the same artifact in a sibling command earlier in the same script. IDs can change between TMC env states.
- **Treat user-supplied env vars and config values as truth for *paths* and *secrets*, but never for *project state*.** `talend.properties` tells you the workspace name; it does not tell you what's currently deployed there.

### For documentation commands

- **Inventory awareness is fine.** If a project maintains `docs/joblets/` listing shared joblets and which interfaces call each one, `/document-interface` may consult that inventory before deep-reading. But before producing a description of a joblet's *current behaviour*, it must read the joblet's `.item` file in the current branch.
- **Mark cached claims explicitly.** When a doc references an inventory entry rather than the live job, note it ("see joblet inventory") so the reader knows where the trust boundary is.
- **Re-derive on every doc refresh.** Update-diff mode re-reads the deployed jobs from scratch — it doesn't take the previous doc as ground truth for what the jobs *do*.

## When this principle bites

Common ways developers (and Claude) violate it:

- Caching TMC task IDs in a shell script and reusing them in a later step "to save a round-trip". *Forbidden* — re-discover by name.
- Reading the last commit's interface doc to figure out what the API does, instead of opening the `.item` files. *Forbidden* for any command that may trigger a deploy.
- Asking the user "which ports do your APIs use" once and persisting the answer in `talend.properties`. *Forbidden* for operational commands — they pull port assignment from `/run-config` live. (The user's project may still keep a port table in its own `docs/` for human reference; ops commands ignore it.)
- Trusting a local `talend.framework.path` to point to the correct version of an external config without confirming the framework repo's HEAD matches the expected branch. *Allowed* only as a path hint; the resolution that matters happens at job-runtime, not at command-time.

## How to spot which side a new command falls on

If the command's output is the basis for an irreversible production action (deploy, promote, redeploy) → operational, must read live.

If the command's output is a Markdown file or a chat response → documentation, may cache but should explicitly note staleness boundaries.

When unsure, choose operational. Wrong direction here is a wrong-by-default-safer choice: re-reading the source is rarely the *wrong* thing to do, only sometimes the slower one.
