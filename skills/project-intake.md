---
description: Offline-analyse a Talend project into a canonical JSON inventory and an Excel report for upgrade/monitoring/review estimation.
argument-hint: [project-path]
---

Run an offline intake of the Talend project at `$1`. This produces a canonical JSON inventory (every artifact, the external systems it touches, proposed logical interfaces, estimated complexity, and a gaps worklist) and renders it to a colour-coded Excel report. No credentials and no running TMC are needed — it reads a plain Git checkout.

This command runs **interactively in the main chat**. The method behind it is documented in [`knowledge/patterns/project-intake.md`](../knowledge/patterns/project-intake.md) — read it if you need the model (four phases, provenance discipline, interface-vs-artifact, the canonical-JSON shape).

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

This is **pure rendering** — every value comes straight from the JSON, so the two can never disagree. The workbook has nine sheets (Summary, Infrastructure, Interfaces, Artifacts, Systems, System Read-Write, Complexity, Orchestration (TMC), Gaps). Most data sheets (Infrastructure, Interfaces, Artifacts, Systems, Orchestration (TMC), Gaps) carry a *Provenance* column colour-coded static (green) / tmc (blue) / manual (amber); the Summary sheet shows a provenance legend, and Complexity and System Read-Write are derived views without one.

`openpyxl` is required **only here** (the phase-1 analyzer needs nothing). If it is missing, `pip install openpyxl` — see `INSTALL.md`.

## Step 4 — Review the Gaps with the user

Open the **Gaps** sheet (or the `gaps[]` array) and walk it with the user. Each gap has a kind, a reference, a description, and a ready-to-ask `suggested_question` — these are everything the static pass could not resolve: context-driven connection hosts shown as `(unresolved)`, unknown components, unresolved `tRunJob` targets, and ambiguous interface clusters.

Explain what static analysis deliberately leaves to the follow-up phases (neither is built yet):

- **TMC enrichment (phase 3)** would add environments, engines, and the **plans** — which jobs actually run together and on what cadence — plus execution statistics. These come from Talend Management Console, not from code.
- **Manual capture (phase 4)** resolves the gaps: real hostnames behind context variables, what an unknown component talks to, confirming/renaming the proposed interfaces, and non-Talend flows the code cannot reveal.

The `environments[]`, `infrastructure{}`, and `tmc{}` structures in the JSON are reserved-empty placeholders for exactly this.

## Step 5 — Caveat: complexity is uncalibrated

State this plainly to the user. The complexity buckets (Very Simple … Very Complex) are **estimated, uncalibrated** until the tool is fitted to a real project against a Talend Audit export — every block carries `calibrated: false`. Treat them as relative ordering (heavier artifacts score strictly higher), not as a precise effort figure. Likewise, the **interfaces are `proposed`**, inferred from structure — they are a starting point for the phase-4 conversation, not confirmed groupings.
