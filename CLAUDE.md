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
