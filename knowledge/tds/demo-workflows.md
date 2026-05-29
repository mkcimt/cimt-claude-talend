# TDS demo workflows with `tds_ops.py`

How to stand up (and tear down) a Talend Data Stewardship demo from the CLL.
Tool: [`tools/tds_ops.py`](../../tools/tds_ops.py). Prereq: `tds.token`,
`tds.base_url`/`tds.region`, `tds.user_email` configured (see
[`api-reference.md`](api-reference.md)). All mutating verbs are **dry-run by
default** — add `--apply` to execute.

## Inspect what exists

```bash
python3 tools/tds_ops.py datamodel list --name demo
python3 tools/tds_ops.py campaign  list                 # owned; --all for every campaign
python3 tools/tds_ops.py campaign  get  <name>
python3 tools/tds_ops.py semantic  list --name email
```

## Stand up a demo (data model + RESOLUTION campaign)

```bash
# 1) data model (built-in product template)
python3 tools/tds_ops.py datamodel create --demo --name demo_products --apply

# 2) campaign referencing it (RESOLUTION workflow template)
python3 tools/tds_ops.py campaign create --demo --datamodel demo_products \
        --name demo-products-resolution --apply

# 3) optional: a custom semantic type (sandbox->draft->publish in one go)
python3 tools/tds_ops.py semantic create --demo --name DEMO_CODE --apply
```

Drop `--apply` first to preview the exact request bodies. Use `--file body.json`
instead of `--demo` for fully custom models/campaigns (e.g. MERGING / GROUPING /
ARBITRATION campaigns, whose workflows differ from the RESOLUTION template).

## Seed tasks (records) — not via this tool

Tasks are loaded into a campaign with the Studio component
`tDataStewardshipTaskInput` (or the UI), not the REST API — see
[`known-gaps.md`](known-gaps.md). Create the campaign here, then run a small
Studio job to push demo records as tasks.

## Tear down (clean, repeatable)

Order matters — a data model can't be deleted while a campaign references it:

```bash
python3 tools/tds_ops.py campaign  delete demo-products-resolution --apply
python3 tools/tds_ops.py datamodel delete demo_products            --apply
python3 tools/tds_ops.py semantic  delete <semantic-id>            --apply
```

Created objects are logged to `.claude/tmp/tds-run.json` (gitignored) so you can
see what a run produced.

## Naming

- Data model names allow underscores / mixed case (`demo_products`).
- **Campaign names must match `^[a-z][a-z\d-]*$`** — lowercase, digits, hyphens, no underscores.
- The `--demo` templates auto-namespace as `cimt_demo_<ts>` / `cimt-demo-<ts>` when `--name` is omitted.
