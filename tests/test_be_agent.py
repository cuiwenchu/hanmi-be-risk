import copy
import os
import tempfile
import unittest


os.environ.setdefault("PIPELINE58_ADMIN_PASSWORD", "test-only-password")
os.environ.setdefault("PIPELINE58_DATA_HOME", tempfile.mkdtemp(prefix="hanmi-be-agent-"))
os.environ["BE_AGENT_OLLAMA_MODEL"] = ""

from pipeline58_local.app import (  # noqa: E402
    BE_AGENT_LOCKED_FIELDS,
    _be_agent_apply_patch,
    _be_agent_build_patch,
    _be_agent_keyword_intent,
)


class BeAgentSafetyTests(unittest.TestCase):
    def setUp(self):
        self.request = {
            "reference": {
                "solubility_mg_ml": 0.018,
                "particle_size_um": 18,
                "dissolution_30min_pct": 88,
                "compression_force_kn": 10,
                "dissolution_profile": "5,28\n10,49\n15,67\n30,88\n45,94",
                "excipients": [
                    {"role": "disintegrant", "amount_pct": 4.5},
                    {"role": "lubricant", "amount_pct": 1.4},
                ],
            },
            "test": {
                "solubility_mg_ml": 0.011,
                "particle_size_um": 42,
                "dissolution_30min_pct": 70,
                "compression_force_kn": 15,
                "dissolution_profile": "5,16\n10,31\n15,48\n30,70\n45,82",
                "excipients": [
                    {"role": "disintegrant", "amount_pct": 2.5},
                    {"role": "lubricant", "amount_pct": 1.4},
                ],
            },
        }
        self.result = {
            "summary": {
                "auc_ratio": 0.82,
                "cmax_ratio": 0.73,
                "f2": 35,
                "risk": "High",
            }
        }

    def test_mixed_metric_request_keeps_auc_and_raises_cmax(self):
        message = "Cmax\ub97c \uc870\uae08 \ub192\uc774\uace0 AUC\ub294 \uc720\uc9c0\ud574\uc918"
        intent = _be_agent_keyword_intent(message)
        patch = _be_agent_build_patch(self.request, self.result, intent)

        self.assertEqual(intent["goals"], ["raise_cmax", "preserve_auc"])
        self.assertNotIn("solubility_mg_ml", patch["fields"])
        self.assertIn("particle_size_um", patch["fields"])
        self.assertLess(patch["fields"]["particle_size_um"], 42)

    def test_locked_api_fields_are_never_written(self):
        intent = _be_agent_keyword_intent(
            "pKa\uc640 \uacb0\uc815\ud615\uc744 \ubc14\uafd4\uc918"
        )
        patch = _be_agent_build_patch(self.request, self.result, intent)

        self.assertIn("pka_acid", intent["locked_requests"])
        self.assertIn("polymorph", intent["locked_requests"])
        self.assertFalse(BE_AGENT_LOCKED_FIELDS.intersection(patch["fields"]))

    def test_applying_patch_does_not_mutate_original_request(self):
        original = copy.deepcopy(self.request)
        intent = _be_agent_keyword_intent("raise Cmax slightly and keep AUC")
        patch = _be_agent_build_patch(self.request, self.result, intent)
        candidate = _be_agent_apply_patch(self.request, patch)

        self.assertEqual(self.request, original)
        self.assertNotEqual(candidate["test"], original["test"])


if __name__ == "__main__":
    unittest.main()
