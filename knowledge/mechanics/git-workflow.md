# Git Workflow with Talend Studio

## Feature branch discipline

Before any file-edit (code, docs, `.claude/` config, scripts — anything that touches the working tree): check the current branch with `git branch --show-current`. If on `master` / `main` → **create a feature branch first** per project convention (`feature/...`, `fix/...`, `docs/...`).

After committing on the branch, **always ask the user** before pushing. Never push without explicit confirmation. Most projects protect their main branch and require a PR — direct commits will be rejected anyway, but more importantly the user wants to control when work becomes visible upstream.

Branch-check is the *first* tool-call when an instruction implies file edits. Do not rely on session-start `gitStatus` snapshots — they go stale within minutes.

## Working alongside Talend Studio

Claude Code and Talend Studio share a working tree when both are pointed at the same project folder. Branch switches by either side affect the other, so:

- **Default**: stay on whatever branch Studio is on. Don't switch branches without checking with the user first.
- **Reading from another branch** does not require a checkout — use `git show <branch>:<path>`, `git diff <branch>...<other>`, `git log <branch>` etc. This covers ~95% of "look at branch X" requests.
- **Working in another branch** (commits, tests, builds that need a checked-out tree) requires a separate **worktree** to avoid disturbing Studio.

## Worktree pattern

```
git worktree add <worktree-path> <branch>
```

Recommended default locations:
- **macOS / Linux**: `~/talend-worktrees/<branch-name>`
- **Windows**: `C:\Talend\worktrees\<branch-name>` (parallel to the Studio installation, avoids polluting the workspace or install folders)

Confirm the path with the user the first time. Remove the worktree when no longer needed:

```
git worktree remove <path>
```

When operating inside a worktree from outside it, prefer `git -C <worktree-path> <command>` over `cd`. This keeps the original shell rooted in Studio's workspace and avoids accidental drift.

## Pre-commit safety

- Never amend the previous commit unless the user explicitly asks.
- Never force-push to a shared branch (`master`, `main`, release) without explicit instruction.
- Never skip hooks (`--no-verify`) unless the user explicitly asks.
- If a pre-commit hook fails, the commit did **not** happen — fix the issue and create a *new* commit. Do not `--amend`.

## What goes in the commit message

Talend Studio writes auto-generated coordinates, version bumps, screenshots into `.item` / `.properties` / `.screenshot` files on every save. Most of these are noise. Commit messages should describe the **functional** change — what the job now does differently — not the file-level churn.

When auto-generating a commit message from a Talend diff, **the `talend-branch-reviewer` agent** (see `agents/`) produces a clean functional summary that filters out Studio noise.
