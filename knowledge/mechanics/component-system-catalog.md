# Component → System Catalog

**A Talend job's name is often meaningless; its components are not.** `tOracleInput` reads Oracle no matter what the job is called. The component catalog maps a `componentName` (plus, when needed, its parameters) to an external **family**, **technology**, and data-flow **direction**, with a **confidence** level — so the analyzer can describe what a job touches without trusting naming conventions.

Source of truth: [`tools/component_catalog.py`](../../tools/component_catalog.py). It is pure lookup logic over the parsed `Node` model from [`tools/talend_item.py`](../../tools/talend_item.py) — no I/O, and it **never raises**.

## The two-stage contract

Classification runs in two stages, deliberately separated by confidence.

1. **Trusted name layer** — for *dedicated vendor* components the `componentName` alone yields family + technology. `tOracleInput`, `tSalesforceOutput`, `tKafkaInput` are unambiguous. **Confidence `high`**, robust even without a real `.item` to read. The full prefix table is data in the module (`_VENDOR`, `_WEB`, `_CAMEL`), longest-prefix-wins so `tMSSqlServer*` beats `tMSSql*`.

2. **Param-key hardening** — *generic* components carry their technology only in a parameter:
   - `tDB*` / `tJDBC*` / `tELT*` — a DB-type dropdown or a JDBC URL,
   - `tMom*` — a messaging endpoint,
   - `cMessagingEndpoint` and Camel endpoints — a URI scheme (`activemq:`, `jms:`, `sftp:` …).

   For these the *family* is still known from the name (`tDB*` ⇒ DB, `tMom*` ⇒ Messaging), but the *technology* is resolved from the node's parameter dict by `resolve_generic_technology()`. **Confidence `medium`** when a technology is found, **`low`** when it falls back to `unknown`.

Two more component classes touch **no** external system:

- **Internal** components — `tMap`, `tJava`, `tFilterRow`, `tLogRow`, Camel processors like `cSetBody`/`cLog`, etc. (`INTERNAL_COMPONENTS`, `_INTERNAL_CAMEL`). Marked `is_internal`, family `internal`, direction `internal`, confidence `high`. After hardening against a real project this set also covers the job-instance/AMC logging components `tJobInstanceStart` / `tJobInstanceEnd`, the classloader helper `tLibraryLoad`, and the in-memory hash cache `tHashRow`; and the prefix families `tJSONDoc*` (in-memory JSON document), `tJobInstance*`, and `tHash*` are treated as internal by prefix (`_INTERNAL_PREFIXES`) so future variants are covered without enumerating each one.
- **Project joblet invocations** — a node whose `componentName` matches a **joblet defined in the same project** is an internal sub-flow invocation, not an external system. The intake (`project_intake.py`, which knows the project's joblet labels) records it in the artifact's `joblets_used` rather than minting a system. (The catalog itself is name-only and has no project context, so this resolution happens one layer up.)
- **Call** components — `tRunJob`, `cTalendJob` (`CALL_COMPONENTS`). These are an edge in the call graph, not a system: `is_call` + `is_internal`, technology `(job call)`.

Anything unrecognised degrades gracefully to family/technology `unknown`, confidence `low` — recorded, never crashed.

`classify_component(name, params)` always returns the same dict shape: `{family, technology, direction, confidence, resolved, is_call, is_internal}`. `resolved` is `True` when a concrete technology was nailed down.

## Main families

A compact view of the families and representative components. The catalog is broader than this — see `_VENDOR` / `_WEB` / `_CAMEL` in the module for the complete list.

| Family | Representative components | Notes |
|---|---|---|
| **DB** | `tOracle*`, `tMSSql*`, `tMysql*`, `tPostgresql*`, `tTeradata*`, `tSnowflake*`, `tRedshift*`, `tSAPHana*`, `tHive*`, `tMongoDB*`, `tCassandra*` | Dedicated = name-resolved. Generic `tDB*`/`tJDBC*`/`tELT*` = param-resolved (family always DB). |
| **File** | `tFile*` (e.g. `tFileInputDelimited`, `tFileOutputDelimited`), `cFile` | Technology = `local file`. |
| **FTP/SFTP** | `tFTP*`, `cFTP`, `cSFTP` | `tFTP*` defaults to FTP; refined to SFTP if a param signals it (see synonym note below). |
| **Messaging** | `tKafka*`, `tSQS*`, `tSNS*`, `cJMS`, `cActiveMQ`, generic `tMom*`, `cMessagingEndpoint` | Generic ones param-resolved from a URI scheme. |
| **Web** | `tREST*`, `tSOAP`, `tHttpRequest`, `tWebService*`, `tESB*`, `cCXFRS`, `cCXF`, `cHttp`, `cRest` | Explicit per-component direction (e.g. `tRESTRequest` = read/provider, `tRESTResponse` = write/provider). |
| **Cloud** | `tS3*`, `tAzureStorage*`, `tAzureFS*` (Data Lake), `tGoogleStorage*`, `tBigQuery*` | Object storage + cloud warehouses. |
| **SaaS** | `tSalesforce*`, `tMarketo*`, `tNetSuite*`, `tDynamicsCRM*`, `tWorkday*` | App connectors. |
| **SAP** | `tSAP*`, `tSAPBW`, `tSAPIDoc`, `tSAPBapi` | Longest-prefix-wins keeps the specific variants ahead of bare `tSAP`. |
| **Mail** | `tSendMail` (SMTP), `tPOP` (POP3), `tIMAP`, `cMail` | |

## Direction

For dedicated and generic components, direction is inferred from the name by `direction_from_suffix()`: `Connection`/`…Commit`/`…Rollback`/`…Close` ⇒ `connection`; an `Output`/`Bulk` token or `…Put`/`Load`/`Save`/`Write`/`CreateTable` ⇒ `write`; an `Input` token or `…Get`/`Fetch`/`List`/`Read` etc. ⇒ `read`; otherwise `both`. Note `Input`/`Output` are matched **anywhere** in the name, because the format suffix follows them (`tFileInputDelimited`, `tOracleOutputBulkExec`). Web components override this with an explicit direction baked into `_WEB`.

## Identity extraction and the `(unresolved)` fallback

Once a component is classified, two helpers pull connection identity out of the same parameter dict, using **synonym sets** rather than hard-coded keys:

- `extract_identity(params)` — fills `host`, `port`, `database`, `schema`, `uri`, `endpoint`, `bucket_or_queue_or_topic`. Each field tries a list of spellings (`IDENTITY_SYNONYMS`): e.g. `host` matches `HOST`/`HOSTNAME`/`SERVER`/`ASHOST`/…, `database` matches `DBNAME`/`SID`/`SERVICE_NAME`/`KEYSPACE`/`WAREHOUSE`/…. **Any field not found degrades to the literal string `(unresolved)`** — never an exception, never a guess.
- `extract_objects(params)` — collects table / file / queue / SObject names from `OBJECT_PARAMS` (`TABLE`, `TABLENAME`, `MODULENAME`, `SOBJECT`, `FILENAME`, `QUEUE`, `TOPIC`, …), deduped and order-preserving.

The synonym approach is what lets the same code handle many vendors whose parameter keys differ. It dovetails with `Node.param(*synonyms)` in [`talend_item.py`](item-file-format.md) (exact → case-insensitive → substring matching).

## ⚠ Parameter key names are convention-based — HARDEN against the first real project

The exact `<elementParameter name="…">` XMI key names this module matches on — `HOST`, `DBNAME`, `URL`, `TABLE`, `DB_VERSION`, `SFTP_SUPPORT`, the JDBC-URL and Camel-URI-scheme patterns, and every entry in `IDENTITY_SYNONYMS` / `OBJECT_PARAMS` / `_JDBC_TECH` / `_CAMEL_SCHEME_TECH` — are **convention-based**. They were written from Talend's documented component model, **not verified against a real `.item` sample**. Component prefixes in the trusted name layer (`tOracleInput`, `tSalesforce*`) are stable; the *parameter keys* of the hardening stage are the soft spot.

**Treat the param-key layer as provisional until calibrated against the first real project.** When a real `.item` is available: dump each generic node's full param dict, confirm the actual key spellings, and extend the synonym lists. A missed key spelling only ever causes a graceful `unknown` / `(unresolved)`, not a crash — but it does mean a system goes undescribed, so this hardening is the highest-value first step on a new engagement.

## Related

- [`item-file-format.md`](item-file-format.md) — how `.item` / `.properties` are read, the `elementParameter` / `nodeData` structures these classifications consume, and the tMap caveats.
- [`artifact-detection.md`](artifact-detection.md) — the companion: how artifacts (job/route/joblet/…) are typed without trusting names. Component classification feeds the route-vs-job prefix histogram used there.
