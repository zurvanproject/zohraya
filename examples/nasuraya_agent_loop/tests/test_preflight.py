import contextlib
import io
import json
import os
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from examples.nasuraya_agent_loop.__main__ import main
from examples.nasuraya_agent_loop.agents_api import check_api_environment, make_client


class PreflightTests(unittest.TestCase):
    def test_missing_sdk_and_key_are_reported_without_network(self):
        with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules, {"openai": None}):
            result = check_api_environment()
        self.assertEqual(result["blockers"], ["missing_api_key", "missing_openai_sdk"])
        self.assertFalse(result["ready_for_live_run"])
        self.assertEqual(result["network_requests"], 0)

    def test_cli_check_needs_neither_output_directory_nor_model(self):
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules, {"openai": None}), \
                contextlib.redirect_stdout(output):
            self.assertEqual(main(["--check-api"]), 2)
        self.assertEqual(json.loads(output.getvalue())["network_requests"], 0)

    def test_key_is_never_in_preflight_output_even_when_client_initialization_fails(self):
        class Broken:
            def __init__(self, **kwargs):
                raise RuntimeError("sensitive sentinel")
        sdk = SimpleNamespace(__version__="test", OpenAI=Broken)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sensitive sentinel"}), \
                patch.dict(sys.modules, {"openai": sdk}):
            result = check_api_environment()
        self.assertTrue(result["key_present"])
        self.assertNotIn("sensitive sentinel", json.dumps(result))

    def test_hidden_key_prompt_refuses_noninteractive_fallback(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(sys.stdin, "isatty", return_value=False):
            with self.assertRaisesRegex(ValueError, "interactive terminal"):
                make_client(prompt_api_key=True)

    def test_missing_key_fails_before_any_sdk_client_is_created(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
                make_client()


if __name__ == "__main__":
    unittest.main()
