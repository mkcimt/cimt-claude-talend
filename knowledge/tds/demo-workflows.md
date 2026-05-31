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

## Seed tasks (records) — via REST

Tasks are created through the campaign-scoped endpoint, so the tool can seed the
worklist directly. Put the records in a JSON file (an array of objects whose keys
match the data-model fields), then:

```bash
# records.json: [ {"Material":"EU-100001","Description":"…","MaterialType":"HAWA",
#                  "BaseUnit":"EA","Plant":"DE01"}, … ]
python3 tools/tds_ops.py task create demo-products-resolution --file records.json --apply
python3 tools/tds_ops.py task list   demo-products-resolution --invalid
```

Created tasks are **assigned to you by default** (`tds.user_email`); use
`--assignee EMAIL` or `--unassigned` to change that. Records with values outside a
field's governed value list (or missing required fields) show up as `valid=false`
— filter them with `task list … --invalid`. State transitions / bulk delete stay
in the UI or Studio (`tDataStewardshipTask*`). See [`known-gaps.md`](known-gaps.md).

## Add a data quality rule (and apply it)

```bash
# create a validation rule (DSEL; server derives the variables from the expression)
python3 tools/tds_ops.py dqrule create --name mm_weight_check \
        --expression "if ((MaterialType == 'FERT')) { GrossWeight > 0 }" --apply

# attach it to a data model, mapping rule variables -> model columns
python3 tools/tds_ops.py dqrule apply mm_weight_check demo_products \
        --map MaterialType=MaterialType --map GrossWeight=GrossWeight --apply

python3 tools/tds_ops.py dqrule list
python3 tools/tds_ops.py dqrule export mm_weight_check --out rules_backup.json
```

Once applied, the campaign's tasks evaluate against the rule — each task carries
`VALID / INVALID / NOT_APPLICABLE` per rule (filter with `task list … --invalid`).
Edit with `dqrule edit <name> --expression "…"`, remove with `dqrule delete <name>`.
Rule language = DSEL (see the qlik-talend skill). Import (the UI button) is a
multipart file upload; export via the verb above gives the import-compatible JSON.

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
