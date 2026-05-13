---
description: Review functional Talend changes on a branch (filters Studio noise, flags risks), then optionally amend the commit message and push.
argument-hint: [branch] [base]
---

Review the Talend changes on branch `$1` against base `${2:-master}`.

If `$1` is empty, review the current working tree (uncommitted + committed changes vs `${2:-master}`) — confirm with the user first that this is what they want.

Delegate the actual review to the **talend-branch-reviewer** subagent via the Agent tool. Pass it:

- The target branch (or `HEAD` if reviewing working tree).
- The base branch.
- The repo root (current working directory).

The subagent will return a structured review. Forward its output to me verbatim — do not summarise or re-interpret. If the subagent reports "no findings", that's a valid result; pass it through.

## After the review — optional push workflow

After delivering the review, ask the user whether to push the branch.

If the user says yes (or clears remaining warnings), proceed as follows:

1. **Draft a commit message** based on the subagent's functional summary. Rules:
   - Language: English
   - Format:
     ```
     Automatic Review & Summary: <short subject, max 72 chars total including prefix>

     - <functional change 1>
     - <functional change 2>
     ...

     Original commit message:
     <original commit message verbatim>
     ```
   - Retrieve the original commit message with `git log -1 --format=%B origin/<branch>` before drafting.
   - Show the draft to the user and wait for explicit approval before doing anything.

2. **Amend the commit** (only after user approves the message).
   The main working tree must not be disturbed (Talend Studio is using it).
   Use a worktree instead:
   ```
   # PowerShell — use git -C <path> for all commands, never cd into the worktree
   git -C <repo-root> worktree add "C:\Talend\worktrees\<branch>" origin/<branch>
   git -C "C:\Talend\worktrees\<branch>" checkout -b <branch>
   git -C "C:\Talend\worktrees\<branch>" commit --amend -m "<approved message>"
   ```

3. **Push** (only after the amend succeeds, and only with user's explicit go-ahead):
   ```
   git -C "C:\Talend\worktrees\<branch>" push --force-with-lease --force-if-includes origin <branch>
   git -C <repo-root> worktree remove "C:\Talend\worktrees\<branch>"
   ```

4. **Do not create the PR.** The user creates it in Azure DevOps manually.

Do **not** skip the approval step. Do **not** push without explicit confirmation.
