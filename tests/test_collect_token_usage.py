import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "collect_token_usage.py"
SPEC = importlib.util.spec_from_file_location("collect_token_usage", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class TokenUsageTests(unittest.TestCase):
    def test_missing_binary_never_attempts_install(self):
        with patch.object(MODULE.shutil, "which", return_value=None):
            result = MODULE.collect_ccusage()
        self.assertFalse(result["available"])
        self.assertEqual(result["coverage"], "unavailable")
        self.assertIn("automatic installation is disabled", result["install_hint"])

    def test_normalize_uses_only_explicit_session_ids(self):
        result = MODULE.normalize_ccusage({"sessions": [
            {"session_id": "s-1", "model": "model-a", "usage": {"input_tokens": 10, "output_tokens": 2}},
            {"model": "model-a", "usage": {"input_tokens": 99}},
        ]})
        self.assertEqual(result["coverage"], "exact-session")
        self.assertEqual(result["unattributed_records"], 1)
        self.assertEqual(result["exact_session_records"][0]["session_id"], "s-1")
        self.assertEqual(result["exact_session_records"][0]["metrics"]["output_tokens"], 2)

    def test_invalid_json_is_coverage_gap(self):
        completed = type("Result", (), {"returncode": 0, "stdout": "not-json"})()
        with patch.object(MODULE.shutil, "which", return_value="ccusage"):
            result = MODULE.collect_ccusage(runner=lambda *args, **kwargs: completed)
        self.assertEqual(result["coverage"], "unavailable")
        self.assertEqual(result["error"], "ccusage returned invalid JSON")
