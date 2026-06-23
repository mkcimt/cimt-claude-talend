---
description: Offline-analyse a Talend project into a canonical JSON inventory and an Excel report for upgrade/monitoring/review estimation.
argument-hint: [project-path]
---

Run an offline intake of the Talend project at `$1`. This produces a canonical JSON inventory (every artifact, the external systems it touches, proposed logical interfaces, estimated complexity, external-library dependencies, and a gaps worklist) and renders it to a colour-coded Excel report. The static pass needs no credentials and no running TMC — it reads a plain Git checkout, and includes a deterministic breadth pass of static-review findings (lookup/SQL performance, dead code, missing error handling). An optional, strictly **read-only** TMC enrichment (phase 3), an optional LLM semantic-complexity pass, and an optional A+ deep-review pass (the `talend-code-reviewer` agent on the triaged subset) layer on top.

This command runs **interactively in the main chat**. The method behind it is documented in [`knowledge/patterns/project-intake.md`](../knowledge/patterns/project-intake.md) — read it if you need the model (four phases, provenance discipline, interface-vs-artifact, the canonical-JSON shape, read-only-by-construction).

## Step 1 — Locate the Talend project root

- `$1` given → use it. Confirm it is the project root (the folder containing `talend.project`, `process/`, `routes/`, etc.), not a sub-folder.
- `$1` empty → ask the user for the path to the Talend project root.

## Step 2 — Run the static analyzer (phase 1)

From the toolkit's `tools/` directory:

```
python3 tools/project_intake.py <project-path> --out <project-path>/intake.json
```

This is stdlib-only — no dependencies, no network. It writes `intake.json` (the canonical document) and prints a one-line count to stderr.

For a quick console overview without writing the file first, add `--summary`:

```
python3 tools/project_intake.py <project-path> --summary
```

`--summary` prints artifact counts, distinct external systems (with `(unresolved)` markers), proposed-interface and gap counts, and the estimated complexity histogram. Use it to sanity-check the project was scanned correctly before rendering.

## Step 3 — Render the Excel report (phase 2)

```
python3 tools/intake_to_excel.py --in <project-path>/intake.json --out intake.xlsx
```

This is **pure rendering** — every value comes straight from the JSON, so the two can never disagree. The workbook has twelve sheets (Summary, Infrastructure, Interfaces, Artifacts, Systems, System Read-Write, Complexity, Findings, Dependencies, Orchestration (TMC), Deployment, Gaps). Most data sheets (Infrastructure, Interfaces, Artifacts, Systems, Findings, Dependencies, Orchestration (TMC), Deployment, Gaps) carry a *Provenance* column colour-coded static (green) / tmc (blue) / manual (amber); the Summary sheet shows a provenance legend, and Complexity and System Read-Write are derived views without one.

`openpyxl` is required **only here** (the phase-1 analyzer needs nothing). If it is missing, `pip install openpyxl` — see `INSTALL.md`.

If you intend to run the read-only TMC enrichment (Step 4) and/or the LLM pass (Step 5), do them **first** so their facts land in the same `intake.json`, then render the workbook from the enriched JSON — the Orchestration (TMC) sheet and the blue `tmc` rows will be populated.

## Step 4 — (Optional) Enrich with read-only TMC data (phase 3)

If the engagement has TMC access, enrich the inventory with live console state. **This phase is strictly read-only — it never mutates TMC** (the client is GET-only by construction; see the pattern doc). Re-run the analyzer with `--tmc`:

```
python3 tools/project_intake.py <project-path> --tmc --out <project-path>/intake.json
```

- Needs `tmc.pat` (a Talend Cloud Personal Access Token) and `tmc.region` in `.claude/talend.local.properties` (gitignored). A TMC PAT is **not** read-scoped, so prefer a PAT from a **service account with a read-only role** — defence in depth on top of the GET-only client.
- This fills `environments[]`, `infrastructure{}` (workspaces, engines), and `tmc{}` (tasks, plans, summary), and correlates each deployable artifact as **deployed** (own task, with per-environment presence and an `in_prod` flag — prod is the authoritative "what runs" view), **worker** (reachable via a deployed parent's `tRunJob`), or **orphaned** (dead-code candidate). Every fact carries `provenance:"tmc"`.
- Add `--tmc-stats` to also pull **per-task execution statistics** (run counts, success rate, last-run, cadence). This makes many more read calls and is slower — opt in deliberately.
- `tmc.requests_made` in the JSON is the read-only audit count of every GET that was issued.

If there is no TMC access on day one, skip this step; the gaps it would resolve (which jobs truly run together, on what cadence) go to the phase-4 conversation instead.

## Step 5 — (Optional) LLM semantic-complexity pass

The deterministic score in Step 2 **counts** signals; it cannot tell *20 trivial passthrough columns* apart from *10 gnarly ones*. After analysis, for every artifact whose `complexity.needs_llm_review` is `true`, read the artifact's `.item` — the tMap output expressions, any custom `tJava`/`tJavaRow`/`tJavaFlex` code, and the dependencies — and rate its **semantic** complexity, writing the result back into the JSON:

```
complexity.llm_rating = {
  "rating": "very_low | low | moderate | high | very_high",
  "rationale": "<one or two sentences>",
  "risk_factors": ["<short factor>", "..."]
}
```

Leave the deterministic numbers untouched — `llm_rating` sits *alongside* them.

**Rubric (tunable — recalibrate against real test projects):**

- **Many-but-trivial → low.** A wide tMap that is mostly passthrough, `UPCASE`/`trim`, simple type casts, or fixed-value assignments is *low* semantic complexity however many columns it has. High column count alone is not hard.
- **Few-but-gnarly → high.** A handful of outputs built from nested ternaries, lookup chains, cross-variable dependencies (a tMap var feeding another var feeding the output), dynamic/built-up SQL, or non-trivial custom Java is *high* even with few columns.
- **Hard library dependencies weigh heavily.** Hard-coded / version-pinned external jars (and especially version drift across the project) are a **major upgrade-risk factor** — weight them up: an artifact pinning custom or version-specific jars should rarely rate below *moderate*.

State to the user which artifacts you rated and why, and note the rubric is a starting point to be tuned on real test projects.

## Step 6 — (Optional, A+) Deep review of the triaged subset

The intake's review dimension is **two-tier** (see [`knowledge/patterns/project-intake.md`](../knowledge/patterns/project-intake.md), "Findings / review"). Step 2 already ran Tier 1 — the deterministic breadth catalog in `tools/talend_findings.py` — which fills `artifacts[].findings[]` and the top-level `findings{}` rollup with high-precision candidates (`lookup_reload`, `sql_select_star`, `sql_dynamic`, `sql_leading_wildcard`, `inactive_components`, `no_error_handling`). That breadth pass **triages**; it deliberately does **not** decide hard semantic bugs.

For an A+ review, run the depth pass on the triaged subset. Select every artifact where **`complexity.needs_llm_review` is `true`** OR **`artifacts[].findings` is non-empty**, then run `/review-talend-code` (the `talend-code-reviewer` agent) on exactly that subset. That agent is the established DEPTH reviewer — guard completeness, auth-bypass paths, exhaustiveness, symmetry, confirmed bugs — so do not re-implement its checks here; just hand it the right files. Breadth selects; depth reviews.

Fold the confirmed issues into the review narrative you give the user, and optionally back into the JSON as `provenance:"manual"` notes (the deterministic `findings` stay untouched — manual confirmations sit alongside them, mirroring how `llm_rating` sits alongside the deterministic complexity score).

**This is opt-in.** A pure flag-only intake — Tier 1 breadth findings and no depth pass — is a complete, valid result. The depth pass is what lifts a review from "here are the candidate smells" to "here are the confirmed bugs and guard gaps". Note also that **`sql_dynamic` fires often** (context-parametrised SQL is normal Talend); treat it as informational / tunable and do not let it dominate the triage — prefer the `needs_llm_review` flag and the higher-severity categories when choosing what to deep-review.

## Step 7 — Review the Gaps with the user

Open the **Gaps** sheet (or the `gaps[]` array) and walk it with the user. Each gap has a kind, a reference, a description, and a ready-to-ask `suggested_question` — these are everything the earlier phases could not resolve: context-driven connection hosts shown as `(unresolved)`, unknown components, unresolved `tRunJob` targets, and ambiguous interface clusters.

What is left for **manual capture (phase 4)**: real hostnames behind context variables, what an unknown component talks to, confirming/renaming the proposed interfaces, and non-Talend flows the code cannot reveal. These resolutions land in `manual{}` with `provenance:"manual"`.

## Step 8 — Caveat: complexity is uncalibrated

State this plainly to the user. The deterministic complexity buckets (Very Simple … Very Complex) are **estimated, uncalibrated** until the tool is fitted to a real project against a Talend Audit export — every block carries `calibrated: false`. Treat them as relative ordering (heavier artifacts score strictly higher), not as a precise effort figure; the optional `llm_rating` adds semantic nuance but is itself rubric-based, not calibrated. Likewise, the **interfaces are `proposed`**, inferred from structure — a starting point for the phase-4 conversation, not confirmed groupings.
