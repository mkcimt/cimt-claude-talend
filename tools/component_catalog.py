"""
component_catalog.py — map a Talend `componentName` to the external system it
touches, its data-flow direction, and how confident we are.

This is the heart of the *naming-convention-independent* analysis: we never look
at the job/route name (which in real projects is often meaningless), only at the
components a job is built from. `tOracleInput` reads Oracle, full stop — no matter
what the job is called.

Two-stage contract (see `knowledge/mechanics/component-system-catalog.md`):

1. **Trusted name layer** — the componentName alone yields family + technology +
   direction for dedicated components (`tOracleInput`, `tSalesforceOutput`, …).
   High confidence, robust without a real `.item`.
2. **Param-key hardening** — generic components (`tDBInput`, `tJDBCRow`,
   `tMomInput`, `cMessagingEndpoint`) carry their technology only in a parameter
   (a DB type, a JDBC URL, a Camel URI scheme). We resolve those from the node's
   parameter dict, at lower confidence, and fall back to `unknown` (never crash).

No I/O here — pure lookup logic over the parsed `Node` model from
`talend_item.py`. All mappings are data, calibrated against the first real
project.
"""

from __future__ import annotations

import re
from typing import Optional

UNKNOWN = "unknown"
UNRESOLVED = "(unresolved)"

# --------------------------------------------------------------------------- #
# Trusted name layer — dedicated vendor components
# --------------------------------------------------------------------------- #
# Prefix -> (family, technology). Longest prefix wins (checked sorted by length).
_VENDOR: dict[str, tuple[str, str]] = {
    # Relational
    "tOracle": ("DB", "Oracle"),
    "tMSSqlServer": ("DB", "MS SQL Server"),
    "tMSSql": ("DB", "MS SQL Server"),
    "tMysql": ("DB", "MySQL"),
    "tPostgresqlPlus": ("DB", "PostgresPlus"),
    "tPostgresql": ("DB", "PostgreSQL"),
    "tTeradata": ("DB", "Teradata"),
    "tDB2": ("DB", "DB2"),
    "tNetezza": ("DB", "Netezza"),
    "tVertica": ("DB", "Vertica"),
    "tGreenplum": ("DB", "Greenplum"),
    "tSybase": ("DB", "Sybase"),
    "tInformix": ("DB", "Informix"),
    "tAS400": ("DB", "AS/400 (DB2 for i)"),
    "tFirebird": ("DB", "Firebird"),
    "tInterbase": ("DB", "Interbase"),
    "tSQLite": ("DB", "SQLite"),
    "tHSQLDb": ("DB", "HSQLDB"),
    "tMaxDB": ("DB", "MaxDB"),
    "tExasol": ("DB", "Exasol"),
    "tMonetDB": ("DB", "MonetDB"),
    "tSAPHana": ("DB", "SAP HANA"),
    "tSnowflake": ("DB", "Snowflake"),
    "tRedshift": ("DB", "AWS Redshift"),
    "tAzureSqlDataWarehouse": ("DB", "Azure Synapse"),
    "tAzureSql": ("DB", "Azure SQL"),
    "tBigQuery": ("Cloud", "Google BigQuery"),
    # Hadoop / NoSQL / search
    "tHive": ("DB", "Apache Hive"),
    "tImpala": ("DB", "Apache Impala"),
    "tMongoDB": ("DB", "MongoDB"),
    "tCassandra": ("DB", "Cassandra"),
    "tElasticsearch": ("DB", "Elasticsearch"),
    "tNeo4j": ("DB", "Neo4j"),
    "tHBase": ("DB", "HBase"),
    "tCouchbase": ("DB", "Couchbase"),
    "tDynamoDB": ("DB", "AWS DynamoDB"),
    "tAzureCosmosDB": ("DB", "Azure Cosmos DB"),
    "tCosmosDB": ("DB", "Cosmos DB"),
    # Cloud object storage
    "tS3": ("Cloud", "AWS S3"),
    "tAzureStorage": ("Cloud", "Azure Storage"),
    "tAzureFS": ("Cloud", "Azure Data Lake"),
    "tGoogleStorage": ("Cloud", "Google Cloud Storage"),
    "tGSStorage": ("Cloud", "Google Cloud Storage"),
    "tGoogleDrive": ("Cloud", "Google Drive"),
    # Messaging
    "tKafka": ("Messaging", "Apache Kafka"),
    "tSQS": ("Messaging", "AWS SQS"),
    "tSNS": ("Messaging", "AWS SNS"),
    # SaaS / apps
    "tSalesforce": ("SaaS", "Salesforce"),
    "tMarketo": ("SaaS", "Marketo"),
    "tNetSuite": ("SaaS", "NetSuite"),
    "tMicrosoftDynamicsCRM": ("SaaS", "Dynamics CRM"),
    "tDynamicsCRM": ("SaaS", "Dynamics CRM"),
    "tWorkday": ("SaaS", "Workday"),
    "tSAPBW": ("SAP", "SAP BW"),
    "tSAPIDoc": ("SAP", "SAP (IDoc)"),
    "tSAPBapi": ("SAP", "SAP (BAPI)"),
    "tSAP": ("SAP", "SAP"),
    # Mail
    "tSendMail": ("Mail", "SMTP"),
    "tPOP": ("Mail", "POP3"),
    "tIMAP": ("Mail", "IMAP"),
}

# FTP / SFTP — Talend uses tFTP* with an SFTP toggle (technology refined from params).
_FTP_PREFIX = "tFTP"
# Local-file components.
_FILE_PREFIX = "tFile"
# Web/service components needing direction/technology overrides.
_WEB: dict[str, tuple[str, str, str]] = {  # name/prefix -> (family, technology, direction)
    "tRESTClient": ("Web", "REST (client)", "both"),
    "tRESTRequest": ("Web", "REST (provider)", "read"),
    "tRESTResponse": ("Web", "REST (provider)", "write"),
    "tREST": ("Web", "REST", "both"),
    "tHttpRequest": ("Web", "HTTP", "both"),
    "tSOAP": ("Web", "SOAP", "both"),
    "tWebServiceInput": ("Web", "SOAP", "read"),
    "tWebService": ("Web", "SOAP", "both"),
    "tESBConsumer": ("Web", "ESB consumer (SOAP/REST)", "both"),
    "tESBProviderRequest": ("Web", "ESB provider", "read"),
    "tESBProviderResponse": ("Web", "ESB provider", "write"),
}

# Camel (route) components, c* prefix.
_CAMEL: dict[str, tuple[str, str, str]] = {  # prefix -> (family, technology, direction)
    "cFile": ("File", "local file", "both"),
    "cFTP": ("FTP", "FTP/SFTP", "both"),
    "cSFTP": ("FTP", "SFTP", "both"),
    "cJMS": ("Messaging", "JMS", "both"),
    "cMQConnectionFactory": ("Messaging", "JMS/MQ", "connection"),
    "cActiveMQ": ("Messaging", "ActiveMQ", "connection"),
    "cCXFRS": ("Web", "REST (CXF)", "both"),
    "cCXF": ("Web", "SOAP (CXF)", "both"),
    "cHttp": ("Web", "HTTP", "both"),
    "cRest": ("Web", "REST", "both"),
    "cMail": ("Mail", "SMTP/IMAP", "both"),
}

# Component-name prefixes that are always in-job/internal (no external system).
# tJSONDoc* build a JSON document in memory; tJobInstance* are Talend's job-instance
# logging/AMC components; tHash* are the in-memory hash cache.
_INTERNAL_PREFIXES = ("tJSONDoc", "tJobInstance", "tHash")

# Components that touch NO external system — pure in-job logic / control flow.
INTERNAL_COMPONENTS: set[str] = {
    "tMap", "tXMLMap", "tHMap", "tJava", "tJavaRow", "tJavaFlex", "tLogRow",
    "tHashRow", "tLibraryLoad", "tJobInstanceStart", "tJobInstanceEnd",
    "tFlowToIterate", "tIterateToFlow", "tRunJob", "tFixedFlowInput", "tFilterRow",
    "tFilterColumns", "tAggregateRow", "tAggregateSortedRow", "tSortRow", "tUniqRow",
    "tReplicate", "tUnite", "tHashInput", "tHashOutput", "tBufferInput", "tBufferOutput",
    "tContextLoad", "tContextDump", "tSetGlobalVar", "tPrejob", "tPostjob", "tDie",
    "tWarn", "tAssert", "tAssertCatcher", "tLogCatcher", "tStatCatcher",
    "tFlowMeterCatcher", "tFlowMeter", "tStatistics", "tSleep", "tChronometerStart",
    "tChronometerStop", "tRowGenerator", "tSampleRow", "tNormalize", "tDenormalize",
    "tSplitRow", "tConvertType", "tReplace", "tReplaceList", "tExtractDelimitedFields",
    "tExtractRegexFields", "tExtractXMLField", "tExtractJSONFields", "tWriteJSONField",
    "tWriteXMLField", "tMemorizeRows", "tJoin", "tMatchGroup", "tSchemaComplianceCheck",
    "tPivotToColumnsDelimited", "tAddCRCRow", "tMsgBox", "tLoop", "tForeach",
    "tInfiniteLoop", "tWaitForSqlData", "tWaitForFile",
}
# Internal Camel/ESB processors (no external system).
_INTERNAL_CAMEL: set[str] = {
    "cConfig", "cSetBody", "cSetHeader", "cSetProperty", "cLog", "cProcessor",
    "cBean", "cJavaDSLProcessor", "cSplitter", "cAggregator", "cContentEnricher",
    "cDelayer", "cExchangePattern", "cMessageFilter", "cMulticast", "cLoadBalancer",
    "cRoutingSlip", "cThrottler", "cWireTap", "cDataset",
}

# Components that represent a *job/route call* — an edge in the call graph, not a system.
CALL_COMPONENTS: set[str] = {"tRunJob", "cTalendJob"}

# --------------------------------------------------------------------------- #
# Parameter synonym sets (for identity extraction; param-key hardening stage)
# --------------------------------------------------------------------------- #
IDENTITY_SYNONYMS: dict[str, list[str]] = {
    "host": ["HOST", "HOSTNAME", "SERVER", "SERVER_NAME", "ASHOST", "NODES", "ACCOUNT"],
    "port": ["PORT"],
    "database": ["DBNAME", "DATABASE", "DB", "SID", "SERVICE_NAME", "KEYSPACE", "WAREHOUSE"],
    "schema": ["SCHEMA", "SCHEMA_DB"],
    "uri": ["URI", "URL", "JDBC_URL", "ENDPOINT", "WSDL", "REST_API_URL"],
    "endpoint": ["ENDPOINT", "URI", "URL"],
    "bucket_or_queue_or_topic": [
        "BUCKET", "BUCKET_NAME", "CONTAINER", "CONTAINER_NAME",
        "QUEUE", "TOPIC", "DESTINATION", "MESSAGE_TYPE",
    ],
}
# Object names (tables / files / queues / SObjects) — used to enrich systems[].objects.
OBJECT_PARAMS: list[str] = [
    "TABLE", "TABLENAME", "DBTABLE", "MODULENAME", "SOBJECT", "COLLECTION",
    "COLUMN_FAMILY", "INDEX", "FILENAME", "QUEUE", "TOPIC",
]

_URI_SCHEME_RE = re.compile(r"^\s*(\w[\w.+-]*?)://", re.IGNORECASE)
_CAMEL_SCHEME_RE = re.compile(r"^\s*\"?(\w[\w.+-]*?):", re.IGNORECASE)
_JDBC_RE = re.compile(r"jdbc:([a-z0-9]+):", re.IGNORECASE)

_JDBC_TECH = {
    "oracle": "Oracle", "sqlserver": "MS SQL Server", "jtds": "MS SQL Server",
    "mysql": "MySQL", "mariadb": "MariaDB", "postgresql": "PostgreSQL",
    "db2": "DB2", "teradata": "Teradata", "snowflake": "Snowflake",
    "hive2": "Apache Hive", "hive": "Apache Hive", "redshift": "AWS Redshift",
    "sap": "SAP HANA", "vertica": "Vertica", "netezza": "Netezza",
}
_CAMEL_SCHEME_TECH = {
    "jms": ("Messaging", "JMS"), "activemq": ("Messaging", "ActiveMQ"),
    "amqp": ("Messaging", "AMQP"), "rabbitmq": ("Messaging", "RabbitMQ"),
    "kafka": ("Messaging", "Apache Kafka"), "sjms": ("Messaging", "JMS"),
    "file": ("File", "local file"), "ftp": ("FTP", "FTP"), "ftps": ("FTP", "FTPS"),
    "sftp": ("FTP", "SFTP"), "http": ("Web", "HTTP"), "http4": ("Web", "HTTP"),
    "https": ("Web", "HTTPS"), "cxf": ("Web", "SOAP (CXF)"), "cxfrs": ("Web", "REST (CXF)"),
    "sql": ("DB", UNKNOWN), "jdbc": ("DB", UNKNOWN),
}


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def direction_from_suffix(name: str) -> str:
    """Best-effort data-flow direction from the component name.

    Detects "Input"/"Output" as tokens *anywhere* in the name, because the format
    suffix follows them (`tFileInputDelimited`, `tOracleOutputBulkExec`).
    """
    if "Connection" in name or name.endswith(("Commit", "Rollback", "Close")):
        return "connection"
    if "Output" in name or "Bulk" in name or name.endswith(("Put", "Load", "CreateTable", "Save", "Write")):
        return "write"
    if "Input" in name or name.endswith(("Get", "Fetch", "List", "Exist", "RowCount", "Read")):
        return "read"
    if name.endswith(("Row", "SP", "SCD", "ELT")):
        return "both"
    return "both"


def resolve_generic_technology(name: str, params: dict[str, str]) -> tuple[str, str, str]:
    """Resolve technology for generic components from their params.

    Returns (family, technology, confidence). Used for tDB*/tJDBC*/tMom*/
    cMessagingEndpoint where the name alone gives only the family.
    """
    values = " ".join(v for v in params.values() if v)

    # JDBC URL anywhere in the params (tJDBC*, tDB* with a URL).
    m = _JDBC_RE.search(values)
    if m:
        tech = _JDBC_TECH.get(m.group(1).lower(), UNKNOWN)
        return ("DB", tech, "medium" if tech != UNKNOWN else "low")

    # Explicit DB type discriminator (tDB* "Database" dropdown). NOTE: do NOT use
    # "DATABASE" here — that holds the database *name* (see IDENTITY_SYNONYMS), not
    # the DB *type*; a DB literally named "oracle_stage" must not classify as Oracle.
    for key in ("DB_VERSION", "TYPE", "DB_TYPE", "DBTYPE"):
        val = params.get(key, "")
        if val:
            for token, tech in _JDBC_TECH.items():
                if token in val.lower():
                    return ("DB", tech, "medium")

    # Camel endpoint URI scheme (cMessagingEndpoint and friends).
    for v in params.values():
        sm = _CAMEL_SCHEME_RE.match(v or "")
        if sm:
            fam_tech = _CAMEL_SCHEME_TECH.get(sm.group(1).lower())
            if fam_tech:
                fam, tech = fam_tech
                return (fam, tech, "medium" if tech != UNKNOWN else "low")

    return (UNKNOWN, UNKNOWN, "low")


def classify_component(name: str, params: Optional[dict[str, str]] = None) -> dict:
    """Classify one component.

    Returns a dict: {family, technology, direction, confidence, resolved, is_call,
    is_internal}. Never raises; an unrecognised component degrades to
    family/technology = "unknown", confidence "low".
    """
    params = params or {}
    out = {
        "family": UNKNOWN, "technology": UNKNOWN, "direction": "both",
        "confidence": "low", "resolved": False, "is_call": False, "is_internal": False,
    }
    if not name:
        return out

    # Call components (edge, not a system).
    if name in CALL_COMPONENTS:
        out.update(is_call=True, is_internal=True, family="internal",
                   technology="(job call)", direction="internal", confidence="high")
        return out

    # Internal logic / control flow.
    if name in INTERNAL_COMPONENTS or name in _INTERNAL_CAMEL or name.startswith(_INTERNAL_PREFIXES):
        out.update(is_internal=True, family="internal", technology="(internal)",
                   direction="internal", confidence="high")
        return out

    # Web / service components (explicit direction).
    for prefix, (fam, tech, direction) in sorted(_WEB.items(), key=lambda kv: -len(kv[0])):
        if name == prefix or name.startswith(prefix):
            out.update(family=fam, technology=tech, direction=direction,
                       confidence="high", resolved=True)
            return out

    # Dedicated vendor components (longest prefix wins).
    for prefix in sorted(_VENDOR, key=len, reverse=True):
        if name.startswith(prefix):
            fam, tech = _VENDOR[prefix]
            out.update(family=fam, technology=tech,
                       direction=direction_from_suffix(name),
                       confidence="high", resolved=True)
            return out

    # FTP / SFTP — refine SFTP from a param if present.
    if name.startswith(_FTP_PREFIX):
        tech = "FTP"
        joined = " ".join(params.values()).lower()
        if "sftp" in joined or params.get("SFTP_SUPPORT", "").lower() == "true":
            tech = "SFTP"
        out.update(family="FTP", technology=tech,
                   direction=direction_from_suffix(name), confidence="high", resolved=True)
        return out

    # Local file components.
    if name.startswith(_FILE_PREFIX):
        out.update(family="File", technology="local file",
                   direction=direction_from_suffix(name), confidence="high", resolved=True)
        return out

    # Camel dedicated components.
    for prefix, (fam, tech, direction) in sorted(_CAMEL.items(), key=lambda kv: -len(kv[0])):
        if name.startswith(prefix):
            out.update(family=fam, technology=tech, direction=direction,
                       confidence="high", resolved=(tech != UNKNOWN))
            return out

    # Generic DB / messaging / endpoint — resolve from params (param-key hardening).
    if (name.startswith(("tDB", "tJDBC")) or name.startswith("tMom")
            or name.startswith("cMessagingEndpoint") or name.startswith("tELT")):
        fam, tech, conf = resolve_generic_technology(name, params)
        # The family is known from the name even when the technology isn't.
        if name.startswith(("tDB", "tJDBC", "tELT")):
            fam = "DB"
        elif name.startswith("tMom"):
            fam = "Messaging"
        elif fam == UNKNOWN:
            fam = "CamelEndpoint"
        out.update(family=fam, technology=tech, confidence=conf,
                   direction=direction_from_suffix(name), resolved=(tech != UNKNOWN))
        return out

    # Truly unknown — record, never crash.
    return out


def extract_identity(params: dict[str, str]) -> dict:
    """Best-effort connection identity from a node's params. Unfilled -> UNRESOLVED."""
    ident = {k: UNRESOLVED for k in
             ("host", "port", "database", "schema", "uri", "endpoint", "bucket_or_queue_or_topic")}
    for field_name, keys in IDENTITY_SYNONYMS.items():
        for k in keys:
            v = params.get(k)
            if v:
                ident[field_name] = v
                break
    return ident


def extract_objects(params: dict[str, str]) -> list[str]:
    """Table / file / queue names referenced by a node (deduped, order-preserving)."""
    seen: list[str] = []
    for k in OBJECT_PARAMS:
        v = params.get(k)
        if v and v not in seen:
            seen.append(v)
    return seen


# --------------------------------------------------------------------------- #
# Self-test
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    c = classify_component("tOracleInput")
    assert c["technology"] == "Oracle" and c["direction"] == "read" and c["confidence"] == "high"

    c = classify_component("tMSSqlOutput")
    assert c["technology"] == "MS SQL Server" and c["direction"] == "write"

    c = classify_component("tSnowflakeConnection")
    assert c["technology"] == "Snowflake" and c["direction"] == "connection"

    c = classify_component("tSalesforceInput")
    assert c["family"] == "SaaS" and c["technology"] == "Salesforce"

    c = classify_component("tFTPPut", {"SFTP_SUPPORT": "true"})
    assert c["family"] == "FTP" and c["technology"] == "SFTP" and c["direction"] == "write"

    c = classify_component("tFileInputDelimited")
    assert c["family"] == "File" and c["direction"] == "read"

    c = classify_component("tRESTRequest")
    assert c["technology"] == "REST (provider)" and c["direction"] == "read"

    c = classify_component("tMap")
    assert c["is_internal"] and c["direction"] == "internal"

    c = classify_component("tRunJob")
    assert c["is_call"] and c["is_internal"]

    # Generic DB resolved from a JDBC URL.
    c = classify_component("tDBInput", {"URL": "jdbc:postgresql://h:5432/db"})
    assert c["technology"] == "PostgreSQL" and c["confidence"] == "medium"

    # Generic DB with no discriminator -> unknown but family DB.
    c = classify_component("tDBInput", {"FOO": "bar"})
    assert c["family"] == "DB" and c["technology"] == "unknown" and c["confidence"] == "low"

    # A database NAMED after a vendor must NOT be misread as that vendor's type.
    c = classify_component("tDBInput", {"DATABASE": "mariadb_reporting"})
    assert c["family"] == "DB" and c["technology"] == "unknown" and c["resolved"] is False, c

    # tJSONDoc* / tJobInstance* / tHashRow are internal (no external system).
    for name in ("tJSONDocOpen", "tJobInstanceStart", "tHashRow"):
        assert classify_component(name)["is_internal"], name

    # Camel endpoint resolved from URI scheme.
    c = classify_component("cMessagingEndpoint", {"URI": '"activemq:queue:orders"'})
    assert c["family"] == "Messaging" and c["technology"] == "ActiveMQ"

    # Truly unknown component must not crash.
    c = classify_component("tWeirdCustomThing")
    assert c["technology"] == "unknown" and c["confidence"] == "low"

    ident = extract_identity({"HOST": "h1", "DBNAME": "STG"})
    assert ident["host"] == "h1" and ident["database"] == "STG" and ident["port"] == "(unresolved)"

    objs = extract_objects({"TABLE": "dbo.parts", "QUERY": "..."})
    assert objs == ["dbo.parts"]

    print("component_catalog.py self-test passed")
