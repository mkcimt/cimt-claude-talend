"""Smoke test for the Excel renderer. Skipped when openpyxl is not installed
(the renderer is an optional, phase-2-only dependency)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import project_intake as pi  # noqa: E402
import intake_to_excel as xl  # noqa: E402
from test_project_intake import build_fixture  # noqa: E402

try:
    import openpyxl  # noqa: F401
    HAVE = True
except ImportError:
    HAVE = False


@unittest.skipUnless(HAVE, "openpyxl not installed")
class TestExcelRenderer(unittest.TestCase):
    def test_render_produces_expected_sheets(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            build_fixture(root)
            doc = pi.analyze(root)
            out = root / "intake.xlsx"
            xl.render(doc, out)
            self.assertTrue(out.exists() and out.stat().st_size > 0)

            wb = openpyxl.load_workbook(out)
            for name in ("Summary", "Infrastructure", "Interfaces", "Artifacts",
                         "Systems", "System Read-Write", "Complexity",
                         "Orchestration (TMC)", "Gaps"):
                self.assertIn(name, wb.sheetnames)

            # Artifacts sheet has a header row + one row per artifact.
            ws = wb["Artifacts"]
            self.assertEqual(ws.cell(row=1, column=1).value, "Name")
            self.assertEqual(ws.max_row - 1, len(doc["artifacts"]))

            # Systems sheet lists Oracle.
            techs = {wb["Systems"].cell(row=r, column=2).value
                     for r in range(2, wb["Systems"].max_row + 1)}
            self.assertIn("Oracle", techs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
