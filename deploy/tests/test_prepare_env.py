import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("prepare_env", Path(__file__).resolve().parents[1] / "prepare_env.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PrepareEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.env = self.root / ".env"
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    @staticmethod
    def missing(root, environment, *, probe):
        if probe:
            return {"services": {"envcheck": {"environment": {"POSTGRES_PASSWORD": ""}}}}
        return {"volumes": {"postgres_data": {"name": "isolated_postgres_data"}}}

    def test_initial_password_preserves_other_settings_and_is_private(self):
        original = b"LLM_API_KEY=keep-this\nRSS_REFRESH_MINUTES=60"
        self.env.write_bytes(original)
        with patch.object(module, "compose_config", side_effect=self.missing), patch.object(module, "run", return_value=""):
            self.assertTrue(module.prepare(self.root))
        content = self.env.read_bytes()
        self.assertTrue(content.startswith(original + b"\n"))
        self.assertRegex(content.decode(), r"POSTGRES_PASSWORD=[0-9a-f]{64}\n$")
        if os.name != "nt":
            self.assertEqual(self.env.stat().st_mode & 0o777, 0o600)

    def test_existing_password_and_file_are_kept_on_repeat(self):
        original = b"POSTGRES_PASSWORD='existing $ and # punctuation'\nLLM_API_KEY=keep\n"
        self.env.write_bytes(original)
        config = {"services": {"envcheck": {"environment": {"POSTGRES_PASSWORD": "existing $ and # punctuation"}}}}
        with patch.object(module, "compose_config", return_value=config), patch.object(module, "run") as run:
            self.assertFalse(module.prepare(self.root))
            self.assertFalse(module.prepare(self.root))
            run.assert_not_called()
        self.assertEqual(self.env.read_bytes(), original)

    def test_existing_volume_without_password_refuses_generation(self):
        self.env.write_bytes(b"LLM_API_KEY=keep\n")
        with patch.object(module, "compose_config", side_effect=self.missing), patch.object(module, "run", return_value="isolated_postgres_data\n"):
            with self.assertRaisesRegex(RuntimeError, "Restore the existing password"):
                module.prepare(self.root)
        self.assertEqual(self.env.read_bytes(), b"LLM_API_KEY=keep\n")

    def test_empty_export_does_not_hide_persisted_password(self):
        os.environ["POSTGRES_PASSWORD"] = ""
        config = {"services": {"envcheck": {"environment": {"POSTGRES_PASSWORD": "persisted"}}}}
        with patch.object(module, "compose_config", return_value=config) as inspect:
            self.assertFalse(module.prepare(self.root))
        self.assertNotIn("POSTGRES_PASSWORD", inspect.call_args.args[1])

    def test_compose_failure_does_not_generate_or_expose_secret(self):
        self.env.write_bytes(b"LLM_API_KEY=keep\n")
        with patch.object(module, "compose_config", side_effect=RuntimeError("configuration check failed")):
            with self.assertRaises(RuntimeError):
                module.prepare(self.root)
        self.assertEqual(self.env.read_bytes(), b"LLM_API_KEY=keep\n")


if __name__ == "__main__":
    unittest.main()
