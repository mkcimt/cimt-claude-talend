---
description: Run a Talend code review on a scope (file, folder, or interface ID). For branch reviews use /review-talend-branch.
argument-hint: [scope]
---

Run a Talend code review on `$1`.

If `$1` is empty, ask the user what to review: a file path, a folder path, or an interface ID (e.g. `i562`).

Delegate to the **talend-code-reviewer** subagent via the Agent tool. Pass:
- `$1` as scope — the agent resolves it (file path, folder, or interface ID; see the agent's Step 1 for the resolution logic).
- A context tag if obvious from the path: `deployed-api-job` for routes/i5xx_apis, `worker-batch-job` for process/, `joblet` for joblets/, `routine` for code/routines/.

Forward the agent's output verbatim. Do not summarise or re-interpret. If the agent says "no findings", that is a valid result — pass it through.

Do not propose fixes. If the user wants a fix after the review, that is a separate ask.
