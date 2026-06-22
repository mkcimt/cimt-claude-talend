"""Offline unit tests for component_catalog.py — the naming-convention-independent
component classifier. Covers the trusted-name layer (dedicated vendor / SaaS /
web / file / camel / internal), the param-key hardening stage (generic DB and
Camel endpoints resolved from params), and graceful degradation for unknown
components. All fixtures are synthetic component names + param dicts.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import component_catalog as cat  # noqa: E402


class TestDedicatedVendor(unittest.TestCase):
    def test_oracle_input_read_high(self):
        c = cat.classify_component("tOracleInput")
        self.assertEqual(c["family"], "DB")
        self.assertEqual(c["technology"], "Oracle")
        self.assertEqual(c["direction"], "read")
        self.assertEqual(c["confidence"], "high")
        self.assertTrue(c["resolved"])

    def test_mssql_output_write(self):
        c = cat.classify_component("tMSSqlOutput")
        self.assertEqual(c["technology"], "MS SQL Server")
        self.assertEqual(c["direction"], "write")

    def test_snowflake_connection(self):
        c = cat.classify_component("tSnowflakeConnection")
        self.assertEqual(c["technology"], "Snowflake")
        self.assertEqual(c["direction"], "connection")

    def test_longest_prefix_wins(self):
        # tMSSqlServer* must beat the shorter tMSSql prefix; both map to MS SQL
        # Server, so assert the family/technology rather than the prefix used.
        c = cat.classify_component("tMSSqlServerInput")
        self.assertEqual(c["technology"], "MS SQL Server")
        self.assertEqual(c["direction"], "read")


class TestSaaS(unittest.TestCase):
    def test_salesforce_input(self):
        c = cat.classify_component("tSalesforceInput")
        self.assertEqual(c["family"], "SaaS")
        self.assertEqual(c["technology"], "Salesforce")
        self.assertEqual(c["direction"], "read")


class TestFtpSftp(unittest.TestCase):
    def test_ftp_plain(self):
        c = cat.classify_component("tFTPGet")
        self.assertEqual(c["family"], "FTP")
        self.assertEqual(c["technology"], "FTP")

    def test_sftp_refined_from_support_param(self):
        c = cat.classify_component("tFTPPut", {"SFTP_SUPPORT": "true"})
        self.assertEqual(c["family"], "FTP")
        self.assertEqual(c["technology"], "SFTP")
        self.assertEqual(c["direction"], "write")

    def test_sftp_refined_from_value_substring(self):
        c = cat.classify_component("tFTPConnection", {"PROTOCOL": "sftp://host"})
        self.assertEqual(c["technology"], "SFTP")
        self.assertEqual(c["direction"], "connection")


class TestFile(unittest.TestCase):
    def test_file_input_delimited_read(self):
        c = cat.classify_component("tFileInputDelimited")
        self.assertEqual(c["family"], "File")
        self.assertEqual(c["technology"], "local file")
        self.assertEqual(c["direction"], "read")

    def test_file_output_write(self):
        c = cat.classify_component("tFileOutputDelimited")
        self.assertEqual(c["family"], "File")
        self.assertEqual(c["direction"], "write")


class TestWeb(unittest.TestCase):
    def test_rest_request_read_provider(self):
        c = cat.classify_component("tRESTRequest")
        self.assertEqual(c["family"], "Web")
        self.assertEqual(c["technology"], "REST (provider)")
        self.assertEqual(c["direction"], "read")

    def test_rest_response_write(self):
        c = cat.classify_component("tRESTResponse")
        self.assertEqual(c["technology"], "REST (provider)")
        self.assertEqual(c["direction"], "write")


class TestInternal(unittest.TestCase):
    def test_tmap_internal(self):
        c = cat.classify_component("tMap")
        self.assertTrue(c["is_internal"])
        self.assertEqual(c["family"], "internal")
        self.assertEqual(c["direction"], "internal")
        self.assertFalse(c["is_call"])

    def test_trunjob_is_call(self):
        c = cat.classify_component("tRunJob")
        self.assertTrue(c["is_call"])
        self.assertTrue(c["is_internal"])
        self.assertEqual(c["direction"], "internal")

    def test_ctalendjob_is_call(self):
        c = cat.classify_component("cTalendJob")
        self.assertTrue(c["is_call"])

    def test_internal_camel_processor(self):
        c = cat.classify_component("cProcessor")
        self.assertTrue(c["is_internal"])


class TestGenericResolvedFromParams(unittest.TestCase):
    def test_db_input_resolved_from_jdbc_url(self):
        c = cat.classify_component("tDBInput", {"URL": "jdbc:postgresql://h:5432/db"})
        self.assertEqual(c["family"], "DB")
        self.assertEqual(c["technology"], "PostgreSQL")
        self.assertEqual(c["confidence"], "medium")
        self.assertTrue(c["resolved"])

    def test_db_input_no_discriminator_family_db_tech_unknown_low(self):
        c = cat.classify_component("tDBInput", {"FOO": "bar"})
        self.assertEqual(c["family"], "DB")
        self.assertEqual(c["technology"], cat.UNKNOWN)
        self.assertEqual(c["confidence"], "low")
        self.assertFalse(c["resolved"])

    def test_db_input_resolved_from_type_discriminator(self):
        c = cat.classify_component("tDBInput", {"DB_VERSION": "MYSQL_5"})
        self.assertEqual(c["family"], "DB")
        self.assertEqual(c["technology"], "MySQL")
        self.assertEqual(c["confidence"], "medium")

    def test_mom_input_family_messaging(self):
        c = cat.classify_component("tMomInput", {"FOO": "bar"})
        self.assertEqual(c["family"], "Messaging")


class TestCamel(unittest.TestCase):
    def test_messaging_endpoint_resolved_from_uri_scheme(self):
        c = cat.classify_component("cMessagingEndpoint", {"URI": '"activemq:queue:orders"'})
        self.assertEqual(c["family"], "Messaging")
        self.assertEqual(c["technology"], "ActiveMQ")

    def test_dedicated_camel_jms(self):
        c = cat.classify_component("cJMS")
        self.assertEqual(c["family"], "Messaging")
        self.assertEqual(c["technology"], "JMS")


class TestUnknown(unittest.TestCase):
    def test_unknown_component_no_crash(self):
        c = cat.classify_component("tWeirdCustomThing")
        self.assertEqual(c["family"], cat.UNKNOWN)
        self.assertEqual(c["technology"], cat.UNKNOWN)
        self.assertEqual(c["confidence"], "low")
        self.assertFalse(c["resolved"])

    def test_empty_name_degrades(self):
        c = cat.classify_component("")
        self.assertEqual(c["technology"], cat.UNKNOWN)
        self.assertFalse(c["is_internal"])


class TestDirectionFromSuffix(unittest.TestCase):
    def test_connection(self):
        self.assertEqual(cat.direction_from_suffix("tOracleConnection"), "connection")
        self.assertEqual(cat.direction_from_suffix("tOracleCommit"), "connection")
        self.assertEqual(cat.direction_from_suffix("tOracleClose"), "connection")

    def test_write(self):
        self.assertEqual(cat.direction_from_suffix("tOracleOutput"), "write")
        self.assertEqual(cat.direction_from_suffix("tOracleOutputBulkExec"), "write")

    def test_read(self):
        self.assertEqual(cat.direction_from_suffix("tFileInputDelimited"), "read")
        self.assertEqual(cat.direction_from_suffix("tOracleRowCount"), "read")

    def test_both_default(self):
        self.assertEqual(cat.direction_from_suffix("tOracleRow"), "both")
        self.assertEqual(cat.direction_from_suffix("tSomethingNeutral"), "both")


class TestExtractIdentity(unittest.TestCase):
    def test_resolves_host_and_database(self):
        ident = cat.extract_identity({"HOST": "h1", "DBNAME": "STG"})
        self.assertEqual(ident["host"], "h1")
        self.assertEqual(ident["database"], "STG")

    def test_unfilled_fields_unresolved(self):
        ident = cat.extract_identity({"HOST": "h1"})
        self.assertEqual(ident["port"], cat.UNRESOLVED)
        self.assertEqual(ident["uri"], cat.UNRESOLVED)

    def test_synonym_first_hit(self):
        # SERVER is a host synonym; HOST is absent.
        ident = cat.extract_identity({"SERVER": "srv"})
        self.assertEqual(ident["host"], "srv")


class TestExtractObjects(unittest.TestCase):
    def test_table_extracted(self):
        self.assertEqual(cat.extract_objects({"TABLE": "dbo.parts", "QUERY": "..."}),
                         ["dbo.parts"])

    def test_dedup_order_preserving(self):
        objs = cat.extract_objects({"TABLE": "t1", "FILENAME": "t1", "QUEUE": "q1"})
        self.assertEqual(objs, ["t1", "q1"])

    def test_empty_when_no_object_params(self):
        self.assertEqual(cat.extract_objects({"HOST": "h"}), [])


if __name__ == "__main__":
    unittest.main()
