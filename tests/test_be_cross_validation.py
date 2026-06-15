import os
import tempfile
import unittest


os.environ.setdefault("PIPELINE58_ADMIN_PASSWORD", "test-only-password")
os.environ.setdefault("PIPELINE58_DATA_HOME", tempfile.mkdtemp(prefix="hanmi-be-cross-"))
os.environ["BE_AGENT_OLLAMA_MODEL"] = ""

from pipeline58_local.app import (  # noqa: E402
    _be_cross_curve_stats,
    _be_cross_validation_compare,
)


def curve(scale=1.0):
    return [
        {"time_h": time, "conc_ng_ml": value * scale}
        for time, value in ((0, 0), (0.5, 12), (1, 20), (2, 17), (4, 10), (8, 3))
    ]


class BeCrossValidationTests(unittest.TestCase):
    def setUp(self):
        self.current_result = {
            "summary": {
                "cmax_ratio": 0.98,
                "auc_ratio": 1.02,
                "tmax_delta_h": 0.2,
                "be_pk_pass": True,
            },
            "reference": {"pbpk": {"concentration_time_curve": curve(1.04)}},
            "test": {"pbpk": {"concentration_time_curve": curve()}},
        }
        self.current_request = {
            "common": {"dose_mg": 10, "route": "po"},
            "development_evidence": {"be_design": {"food_state": "fasted"}},
        }

    def test_curve_statistics_detect_close_profiles(self):
        result = _be_cross_curve_stats(curve(), curve(0.98))

        self.assertTrue(result["available"])
        self.assertGreater(result["correlation"], 0.99)
        self.assertLess(result["nrmse_pct"], 5)

    def test_consistent_external_result(self):
        external = {
            "dose_mg": 10,
            "route": "po",
            "food_state": "fasted",
            "cmax_ratio": 1.0,
            "auc_ratio": 1.01,
            "tmax_delta_h": 0.3,
            "be_pass": True,
            "test_curve": curve(0.99),
            "reference_curve": curve(1.03),
        }
        result = _be_cross_validation_compare(
            "pksim", self.current_result, self.current_request, external
        )

        self.assertEqual(result["status"], "consistent")
        self.assertTrue(result["test_curve_stats"]["available"])
        self.assertEqual(result["tool_label"], "PK-Sim")

    def test_conflicting_be_decision_is_clear(self):
        external = {
            "dose_mg": 10,
            "route": "po",
            "cmax_ratio": 0.79,
            "auc_ratio": 0.78,
            "be_pass": False,
        }
        result = _be_cross_validation_compare(
            "gastroplus", self.current_result, self.current_request, external
        )

        self.assertEqual(result["status"], "conflict")
        self.assertFalse(result["external_be_pass"])

    def test_dose_mismatch_is_not_comparable(self):
        external = {
            "dose_mg": 20,
            "route": "po",
            "cmax_ratio": 0.99,
            "auc_ratio": 1.01,
            "be_pass": True,
        }
        result = _be_cross_validation_compare(
            "pksim", self.current_result, self.current_request, external
        )

        self.assertEqual(result["status"], "not_comparable")
        self.assertTrue(any("剂量不一致" in item for item in result["blockers"]))


if __name__ == "__main__":
    unittest.main()
