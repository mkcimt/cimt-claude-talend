# Talend Cloud — Deployment Modes for Data Services

A Talend Data Service (an artifact published from a job marked as ESB / REST endpoint) can be deployed to Talend Cloud in two structurally different ways. **The choice is configured at the task level in TMC, not in the project artifacts** — you cannot tell from reading the `.item` or the `pom.xml` which mode applies. You can tell from how the task is configured in TMC, or by asking the user.

## Two modes

### A — Microservice on Remote Engine (modern, recommended)

The artifact is wrapped as a standalone Spring-Boot-style microservice, deployed directly to a Talend Remote Engine. Each microservice listens on its own configured port (`run-config.microservicePort`), behind a reverse proxy.

- **Lifecycle endpoint**: `POST /processing/executions` with `{"executable": <taskId>}`.
- **Deploy / undeploy / redeploy** uses the public Processing API. See `microservice-lifecycle.md`.
- **Port-binding** is critical — see `known-bugs.md` for the `cmd_bind` port-null bug and the run-config save/restore workaround.
- **Multi-engine clusters** (typically UAT/PRD): one execution per engine. Undeploy must DELETE all of them.

### B — OSGi bundle on Talend Runtime

The artifact is packaged as an OSGi bundle and deployed into a Talend Runtime instance (Karaf-based). Multiple bundles share the Runtime; lifecycle is controlled via Karaf commands and a different set of TMC endpoints.

- **Lifecycle** goes through Karaf-style bundle commands (`bundle:install`, `bundle:start`, `bundle:stop`) or the TMC UI's Runtime view. The public API surface is different — `POST /processing/executions` does *not* apply.
- **Multiple endpoints share a port** (the Runtime's CXF port).
- **Less common in greenfield projects** — Qlik's recommended path for new data services is the microservice mode.

## How to figure out which mode the project uses

You generally cannot derive this from the project's source. Signals that *can* help:

- The `pom.xml` of the data-service module references `cloudpublisher-maven-plugin` (microservice mode) vs. a `karaf`/`osgi`-flavoured assembly (Runtime mode).
- The job's TMC task has a `run-config` with `microservicePort` set → microservice mode.
- The project has Remote Engines paired in TMC and tasks reference engine clusters → microservice mode.

When none of these are conclusive (e.g. you're looking at a new task and the project hasn't been touched in a while), **ask the user once**. Suggested wording:

> *"Quick check: are the data services in this project deployed as microservices on a Remote Engine, or as OSGi bundles on a Talend Runtime? The deploy and lifecycle commands differ."*

Once answered, persist the answer:

- If it applies to every data service in the project → write it to a one-liner in the project's `docs/conventions/`, e.g. `docs/conventions/deployment-mode.md`, so future sessions don't re-ask.
- If only this developer's perspective is relevant (e.g. they have a personal engine pairing) → user memory.

## Why deployment mode is the ask-once exception

Most Talend patterns *are* derivable from project artifacts (typed components, naming conventions, folder structure) — `cimt-claude-talend` does not pre-declare them in `CLAUDE.md`. The deployment mode is the genuine exception because it lives in TMC's task configuration, not in the project source. So we handle it by ask-once-and-persist instead of upfront declaration.
