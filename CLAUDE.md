# cimt-claude-talend — Project Guide for Claude Code

This repo is the **cimt-claude-talend toolkit**: generic, customer-agnostic Talend knowledge, skills, agents, and Python tooling that gets installed into individual customer Talend projects. It is shared across cimt engagements and may be published. **Nothing in this repo is allowed to be customer-specific.**

## Hard rule — customer-information hygiene before every commit and push

The toolkit is generic by definition. Customer-identifying information must **never** land in it. **Before every `git commit` and before every `git push`, review the staged changes and confirm no customer information has leaked in.**

This is a blocking gate — do it every time, not just when it "feels risky":

1. **Inspect what is actually being committed:** `git diff --cached` (and `git diff` for unstaged work you're about to add). Read it, don't skim.
2. **Look for any customer-identifying token**, including but not limited to:
   - Customer / client names, brand names, subsidiaries, project codenames.
   - Interface IDs, job / route / table / column names, business identifiers that come from a specific customer's system.
   - Hostnames, server names, internal URLs, IPs, environment names, tenant / workspace / region values, database or schema names.
   - File-system paths that reveal a customer or a person.
   - Real data values (orders, parts, prices, persons, emails).
   - Secrets of any kind: PATs, passwords, keys, tokens — these must never be committed anywhere.
3. **If you find any → stop and anonymize** before committing. Generalize the example (`<job_name>`, "a 2-engine RE cluster", "Customer SQL Server") so the knowledge survives without the source. If a real example is genuinely essential to make the point, it still gets anonymized — see [`CONTRIBUTING.md`](CONTRIBUTING.md) ("Avoid project-specific examples … anonymize").
4. **A quick scan helps but does not replace reading the diff.** When you know which customer the knowledge came from, grep the staged diff for that customer's known tokens (names, hostnames, interface prefixes) as a backstop:
   `git diff --cached | grep -niE '<token1>|<token2>|…'` — expect **zero** hits.

When in doubt, treat a string as customer-specific and anonymize it. It is far cheaper to over-generalize a knowledge file than to scrub a customer name out of git history after a push.

## Git workflow

- Work on a **feature branch**, never commit directly to `main`.
- Claude **writes and commits**; **the developer decides when to push** — ask before pushing. (Consistent with [`CONTRIBUTING.md`](CONTRIBUTING.md).)
- Keep unrelated pre-existing working-tree changes out of your commit — stage only the files you touched for the task at hand.

## Where things go

Layer classification is non-negotiable before adding knowledge — see [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full capture flow and [`knowledge/INDEX.md`](knowledge/INDEX.md) for the topic map. In short: only **Layer 2a** (universal Talend truth) and **Layer 2b** (optional patterns) belong in this repo. Layer 3 (project-specific) and Layer 4 (developer-specific) belong in the customer project or in user memory, **never here**.

## `/project-intake` feature — status & open work

A multi-phase project-intake feature is **in progress on branch `feature/project-intake`** (not yet merged to `main`). Method doc: [`knowledge/patterns/project-intake.md`](knowledge/patterns/project-intake.md); skill: [`skills/project-intake.md`](skills/project-intake.md); open items: [`BACKLOG.md`](BACKLOG.md).

**Built (content-complete, 182 offline tests):**
- **Phase 1 — static analyzer** ([`tools/project_intake.py`](tools/project_intake.py)): artifacts (type from XML, never names), systems read/written (from components — [`tools/component_catalog.py`](tools/component_catalog.py)), complexity (deterministic, uncalibrated, + a `needs_llm_review` triage flag — [`tools/talend_complexity.py`](tools/talend_complexity.py)), proposed interfaces (call graph — [`tools/talend_topology.py`](tools/talend_topology.py)), **dependency / upgrade-risk** ([`tools/talend_dependencies.py`](tools/talend_dependencies.py)), **deterministic review findings** ([`tools/talend_findings.py`](tools/talend_findings.py)), and gaps. Output is one canonical JSON; every fact carries `provenance ∈ {static, tmc, manual}`.
- **Phase 2 — Excel** ([`tools/intake_to_excel.py`](tools/intake_to_excel.py), optional `openpyxl`): 12-sheet rendering of the JSON.
- **Phase 3 — read-only TMC enrichment** ([`tools/tmc_client.py`](tools/tmc_client.py) GET-only by construction + [`tools/tmc_intake.py`](tools/tmc_intake.py)): environments/engines/workspaces/tasks/plans, deployed-vs-worker-vs-orphaned correlation, per-environment + prod presence. **Strictly read-only** — the client cannot issue a non-GET request (CI-locked in `tests/test_tmc_client.py`).

**Open / next:**
- **Phase 4 — manual capture** (next): generate a gap-/risk-driven, role-segmented **stakeholder-interview guide** from `gaps[]` + findings, and a **gap round-trip** that folds interview answers into the reserved `manual{}` block (`provenance:"manual"`). The intake produces the fact base; interviews add what code/TMC can't know and confirm the auto-derived assumptions.
- Calibration & tuning (deferred to real test runs): complexity weights/thresholds (currently `calibrated:false`) vs. a Talend Audit export; the `needs_llm_review` / A+ deep-review triage; the findings catalog (`sql_dynamic` over-fires on context-parametrised SQL). See `BACKLOG.md` for the full list incl. ESB-detection `[VALIDATE]` and TMC refinements.
- **History scrub** (separate, security): pre-kit customer tokens still live in old `main` commits — forward-fixed, history not yet rewritten.

### Validating project-intake against a project that already uses this kit — clean-room rule

When **test-running** `/project-intake` against a Talend project that already uses this kit, **explicitly ignore the project's own `CLAUDE.md`, `docs/`, `docs/interfaces/`, `knowledge/`, and any kit-generated documentation.** Derive the intake **purely** from the raw artifacts (`.item` / `.properties` / `talend.project`) and TMC — treat the project as if undocumented. The deterministic analyzer already only reads `.item`/`.properties`; this rule binds the **interactive / LLM steps** (complexity LLM pass, A+ deep review, phase-4) and the operator. Reason: a test run must validate what the analyzer *derives*, not echo pre-existing docs (which would be circular and contaminate the result).
