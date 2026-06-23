# Read-Only TMC Intake Client

**Layer 2a (universal Talend truth).** The read-only TMC client behind `/project-intake` phase 3. It reads live Talend Management Console state to enrich the project inventory and **never mutates it** — you are pointing a tool at a customer's running (often production) environment, so the read-only property is a hard guarantee, not a convention.

- Code: [`tools/tmc_client.py`](../../tools/tmc_client.py) (the GET-only client) and [`tools/tmc_intake.py`](../../tools/tmc_intake.py) (the enrichment that drives it).
- Method context: [`../patterns/project-intake.md`](../patterns/project-intake.md) (the four-phase intake, provenance discipline, deployed/worker/orphaned correlation).
- Driven from the `/project-intake` skill with `--tmc` (and optionally `--tmc-stats`).

## The GET-only guarantee — read-only *by construction*

The guarantee lives in the client, enforced at multiple layers, not assumed from caller discipline:

1. **One verb.** The only public method on `TmcClient` is `get()`. There is no post/put/patch/delete; no code path in the module issues a mutating request.
2. **Single choke point.** Every request funnels through one internal `_request()` that **raises `TmcReadOnlyViolation` on any method other than GET** (belt-and-suspenders) before any network I/O. Each `urllib` request is built with an explicit `method="GET"` and no body.
3. **Allow-list.** Requests are restricted to a defence-in-depth allow-list of read API prefixes; a path outside it is refused before any network call:
   `/orchestration/`, `/processing/`, `/observability/`, `/execution-history/`, `/monitoring/`, `/audit/`.
4. **Self-test.** The module's offline self-test asserts that POST/PUT/PATCH/DELETE are all refused, that an off-allow-list path is refused, and — via source inspection — that *every* `urllib` request the module builds uses GET.

## Why the guarantee can't come from the token

A **TMC Personal Access Token carries its owner's full permissions** — TMC PATs are *not* read-scoped. A PAT minted by a user who can deploy, promote, or delete tasks could in principle do all of that; nothing about the token itself restricts it to reads. The read-only property therefore **cannot** come from the credential — it has to come from the client, which is why the guarantee lives in code (above).

**Recommendation — service account with a read-only role.** For defence in depth, provision the PAT from a **TMC service account that holds only a read-only role**. Then even a hypothetical bug in the client cannot escalate beyond reads, because the credential itself has no write authority. Use a dedicated service account (not a personal login) so the intake's activity is attributable and the token can be rotated/revoked independently.

## What it reads

The enrichment issues read-only GETs against the Orchestration and Processing APIs and maps them into the canonical intake JSON (all `provenance:"tmc"`):

- `GET /orchestration/environments` → `environments[]`
- `GET /orchestration/workspaces` → `infrastructure.workspaces[]`
- `GET /processing/engines` → `infrastructure.engines[]`
- `GET /orchestration/executables/tasks` (paginated) → `tmc.tasks[]`, correlated to artifacts as deployed / per-environment / in-prod
- `GET /orchestration/executables/plans` (paginated) → `tmc.plans[]`
- `GET /orchestration/executables/tasks/{id}/executions` → `tmc.execution_stats[]` — **only** with `--tmc-stats` (many calls, slower)

It then correlates tasks back to the static `artifacts[]` to classify each deployable artifact as **deployed** (own task — with `deployed_in_environments[]` and an `in_prod` flag), **worker** (reachable via a deployed parent's `tRunJob` call graph, no own task), or **orphaned** (neither — a dead-code candidate). Prod is treated as the authoritative "what actually runs" view.

## Audit log

The client records every call it makes (method, URL, status) in an in-memory audit list. The intake surfaces the count as `tmc.requests_made` in the JSON, so an engagement can show exactly how many — and, from the list, which — read requests were issued against the customer's TMC. Auditing is on by default.

## Config

In `.claude/talend.local.properties` (gitignored) or via environment variables:

| Key | Env var | Meaning |
| --- | --- | --- |
| `tmc.pat` | `TALEND_PAT` | Bearer Personal Access Token. **Use a read-only service account.** |
| `tmc.region` | `TALEND_TMC_REGION` | Region slug (e.g. the data-center region), used to build `https://api.<region>.cloud.talend.com`. |
| `tmc.base_url` | `TALEND_TMC_BASE_URL` | Full base-URL override; takes precedence over `tmc.region`. |

The PAT is a secret — it lives only in the gitignored `talend.local.properties` (or the environment) and is never committed.
