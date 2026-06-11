import os
import tempfile
import unittest


os.environ.setdefault("PIPELINE58_ADMIN_PASSWORD", "test-only-password")
os.environ.setdefault("PIPELINE58_DATA_HOME", tempfile.mkdtemp(prefix="hanmi-be-development-"))
os.environ["BE_AGENT_OLLAMA_MODEL"] = ""

from pipeline58_local.app import _be_development_evidence, _be_evidence_f2  # noqa: E402


PROFILE_REFERENCE = "5,28\n10,49\n15,68\n30,86\n45,93\n60,97"
PROFILE_TEST_PASS = "5,27\n10,47\n15,66\n30,84\n45,92\n60,96"
PROFILE_TEST_FAIL = "5,10\n10,22\n15,38\n30,60\n45,73\n60,84"


class BeDevelopmentEvidenceTests(unittest.TestCase):
    def test_f2_requires_three_matched_points(self):
        self.assertFalse(_be_evidence_f2("5,20\n10,40", "5,21\n10,39")["available"])
        self.assertTrue(_be_evidence_f2(PROFILE_REFERENCE, PROFILE_TEST_PASS)["pass"])
        self.assertFalse(_be_evidence_f2(PROFILE_REFERENCE, PROFILE_TEST_FAIL)["pass"])

    def test_complete_evidence_reports_statistics_and_design(self):
        evidence = {
            "reference_identity": {
                "brand_name": "Reference",
                "manufacturer": "Originator",
                "market": "CN",
                "strength": "10/10 mg",
                "reference_status": "reference",
                "verified": True,
            },
            "reference_lots": [
                {"lot_no": "A", "assay_pct": 99.5, "hardness_n": 82, "water_pct": 1.2},
                {"lot_no": "B", "assay_pct": 100.1, "hardness_n": 85, "water_pct": 1.3},
                {"lot_no": "C", "assay_pct": 99.9, "hardness_n": 84, "water_pct": 1.1},
            ],
            "api_components": [
                {
                    "name": "API-1",
                    "salt_form": "free",
                    "polymorph": "A",
                    "d10_um": 8,
                    "d50_um": 18,
                    "d90_um": 40,
                    "solubility_ph12": 0.02,
                    "solubility_ph45": 0.018,
                    "solubility_ph68": 0.015,
                }
            ],
            "dissolution_media": [
                {"medium": medium, "label": medium, "reference_profile": PROFILE_REFERENCE, "test_profile": PROFILE_TEST_PASS}
                for medium in ("ph1.2", "ph4.5", "ph6.8")
            ],
            "process_parameters": {
                "blend_time_min": 12,
                "granulation_endpoint": "torque",
                "drying_temp_c": 55,
                "lod_pct": 1.8,
                "compression_min_kn": 9,
                "compression_max_kn": 12,
                "coating_gain_pct": 2.5,
                "tablet_hardness_n": 84,
            },
            "model_calibration": {
                "enabled": True,
                "reference_cmax": 100,
                "test_cmax": 99,
                "reference_auc": 1000,
                "test_auc": 995,
                "source": "pilot BE",
            },
            "be_design": {
                "food_state": "fasted",
                "study_design": "2x2 crossover",
                "washout_days": 7,
                "subject_n": 36,
                "cv_pct": 28,
                "dropout_pct": 10,
                "target_power_pct": 80,
            },
        }
        result = _be_development_evidence(evidence, {}, auc_ratio=0.995, cmax_ratio=0.99)

        self.assertGreaterEqual(result["readiness_score"], 80)
        self.assertTrue(result["multi_media_pass"])
        self.assertEqual(result["lot_count"], 3)
        self.assertAlmostEqual(result["lot_statistics"]["assay_pct"]["mean"], 99.833, places=3)
        self.assertTrue(result["calibration"]["available"])
        self.assertIsNotNone(result["be_design"]["overall_success_probability_pct"])
        self.assertIsNotNone(result["be_design"]["recommended_subject_n"])

    def test_missing_evidence_is_reported_without_fabricated_values(self):
        result = _be_development_evidence({}, {"be_subject_n": 24, "be_cv_pct": 30}, 1.0, 1.0)

        self.assertEqual(result["readiness_score"], 0)
        self.assertIsNone(result["multi_media_pass"])
        self.assertFalse(result["calibration"]["available"])
        self.assertGreaterEqual(len(result["missing_priorities"]), 5)


if __name__ == "__main__":
    unittest.main()
