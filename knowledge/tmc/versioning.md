---
layer: 2a
---

# Three version axes: Job, Artifact, Task

> A TMC project carries three independent "versions" — the Studio **job version**, the published **artifact version**, and the server-side **task version**. They are constantly confused because all three are just called "version". This file states who bumps each, when, and how they relate.

Verified on TMC EU, Studio/R-code R2025-10, two standard (non-microservice) jobs, 2026-06.

| Axis | Example | Bumped by / when | Where it shows |
|---|---|---|---|
| **Job version** | `0.1` | Developer, manually in Studio | `.item` filename (`..._0.1.item`), **generated Java package** (`<project>.<job>_0_1`), stack traces |
| **Artifact version** | `1.0.2.20251010030828` | Cloud Publisher, on every publish/deploy from Studio | TMC artifact; `artifact.version` in the Orchestration API |
| **Task version** | `3.4` | TMC server, on any task change | `version` in the task GET; `flows[].version` in a plan |

## Job version (Studio, manual)

Bumped only when a developer raises the job version in Studio (right-click → version, or the `M`/`m` buttons). It is **compiled into the generated Java**: the package is `<project>.<job>_<major>_<minor>`. Bumping `0.1` → `0.2` produces a new `..._0.2.item` and a new package.

→ The job version can be read straight off a stack trace (`...<job>_0_1...`).

## Artifact version (TMC, per publish)

Shape: `<major>.<minor>.<patch>.<buildTimestamp>`.

- The semantic part is **seeded from the job version** on the first publishes (job `0.1` → first artifact `0.1.0`) and the `patch` auto-increments on each publish (`0.1.0`, `0.1.1`, `0.1.2`, …). It is **editable** in the publish dialog, so a series can jump from e.g. `0.1.6` to a manually chosen `1.0.0`. Job and artifact versions therefore need **not** match (observed: job `0.1`, artifact `1.0.2`).
- The `buildTimestamp` (format `YYYYDDMMHHMMSS` — note **day before month**) is always appended automatically and is unique per publish; it is the real build identifier. Every publish = one new, immutable artifact version. The full version list of an artifact is returned by the Orchestration API (`GET .../artifacts/{id}` → `versions[]`).

## Task version (TMC, server-managed)

A pure revision counter on the task entity (the binding of an artifact version + run config to an environment/engine). It bumps on **every** task change: binding a new artifact version, editing run config or schedule, re-deploying. It bears no numeric relationship to the job or artifact version (observed: task `8.8` against an artifact with only a handful of published versions). In the task GET it is the `version` field; on a `PUT` it must be **dropped** (server-managed) — see [`task-management.md`](task-management.md) for the mandatory GET→modify→PUT bind pattern.

## How they flow

```
Studio job (0.1)
   │  publish from Studio (Cloud Publisher)
   ▼
Artifact version (1.0.2.<buildTimestamp>)     ← new, immutable, per publish
   │  a task binds ONE specific artifact version
   ▼
Task version (3.4)                            ← bumps on every bind / config change / redeploy
   │  a plan references the task
   ▼
Plan flow (shows the task version + the bound artifact version)
```

## Cross-references

- [`task-management.md`](task-management.md) — task/plan/artifact CRUD; the GET→modify→PUT bind pattern (why `version` must be dropped); promote and deploy flows.
