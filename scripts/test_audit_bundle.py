from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_bundle import audit_bundle  # noqa: E402


class BundleAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sample = json.loads(
            (ROOT / "examples" / "analysis_bundle.sample.json").read_text(encoding="utf-8")
        )

    def test_synthetic_sample_passes(self) -> None:
        self.assertEqual([], audit_bundle(deepcopy(self.sample)))

    def test_broken_references_residual_and_hypothesis_fail(self) -> None:
        broken = deepcopy(self.sample)
        broken["metrics"][0]["source_chain"] = ["SRC-MISSING"]
        broken["calculations"][0]["residual_difference"] = 1.0
        broken["claims"][0]["level"] = "hypothesis"
        broken["claims"][1]["claim_id"] = broken["claims"][0]["claim_id"]
        errors = audit_bundle(broken)
        combined = "\n".join(errors)
        self.assertIn("unknown source", combined)
        self.assertIn("residual exceeds tolerance", combined)
        self.assertIn("hypothesis cannot appear", combined)
        self.assertIn("duplicate claim_id", combined)

    def test_metric_requires_period_currency_unit_and_source(self) -> None:
        broken = deepcopy(self.sample)
        broken["metrics"][0]["period"] = ""
        broken["metrics"][0]["currency"] = ""
        broken["metrics"][0]["unit"] = ""
        broken["metrics"][0]["source_chain"] = []
        errors = "\n".join(audit_bundle(broken))
        for field in ("period", "currency", "unit", "source_chain"):
            self.assertIn(field, errors)


if __name__ == "__main__":
    unittest.main()
