"""Unit tests for github_backup.config."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from github_backup.config import (
    load_config,
    _validate_config,
    _apply_defaults,
    _strip_comments,
    get_output_path,
)


VALID_CONFIG = {
    "output_path": "/tmp/github-backup-test",
    "accounts": [
        {
            "name": "testuser",
            "token": "ghp_realtokenwithsufficientlength",
            "include_orgs": ["all"],
            "exclude_orgs": [],
        }
    ],
}


class TestStripComments(unittest.TestCase):
    def test_strips_underscore_keys(self):
        data = {"key": "value", "_comment": "ignored", "_note": "also ignored"}
        result = _strip_comments(data)
        self.assertEqual(result, {"key": "value"})

    def test_nested_strip(self):
        data = {"outer": {"inner": "val", "_comment": "skip"}}
        result = _strip_comments(data)
        self.assertEqual(result, {"outer": {"inner": "val"}})

    def test_non_dict_passthrough(self):
        self.assertEqual(_strip_comments("string"), "string")
        self.assertEqual(_strip_comments(42), 42)


class TestApplyDefaults(unittest.TestCase):
    def test_missing_retry_gets_defaults(self):
        config = {"output_path": "/tmp", "accounts": []}
        result = _apply_defaults(config)
        self.assertIn("retry", result)
        self.assertEqual(result["retry"]["max_attempts"], 3)
        self.assertEqual(result["retry"]["backoff_seconds"], 5)

    def test_missing_archive_gets_defaults(self):
        config = {"output_path": "/tmp", "accounts": []}
        result = _apply_defaults(config)
        self.assertIn("archive", result)
        self.assertFalse(result["archive"]["enabled"])
        self.assertIsNone(result["archive"]["keep_last"])

    def test_existing_values_preserved(self):
        config = {"retry": {"max_attempts": 5, "backoff_seconds": 10}}
        result = _apply_defaults(config)
        self.assertEqual(result["retry"]["max_attempts"], 5)


class TestValidateConfig(unittest.TestCase):
    def test_valid_config_passes(self):
        """Should not raise for valid config."""
        _validate_config(VALID_CONFIG.copy())

    def test_missing_output_path(self):
        config = {"accounts": [{"name": "x", "token": "ghp_real"}]}
        with self.assertRaises(ValueError) as ctx:
            _validate_config(config)
        self.assertIn("output_path", str(ctx.exception))

    def test_missing_accounts(self):
        config = {"output_path": "/tmp"}
        with self.assertRaises(ValueError) as ctx:
            _validate_config(config)
        self.assertIn("accounts", str(ctx.exception))

    def test_empty_accounts_list(self):
        config = {"output_path": "/tmp", "accounts": []}
        with self.assertRaises(ValueError) as ctx:
            _validate_config(config)
        self.assertIn("accounts", str(ctx.exception))

    def test_account_missing_token(self):
        config = {
            "output_path": "/tmp",
            "accounts": [{"name": "testuser"}],
        }
        with self.assertRaises(ValueError) as ctx:
            _validate_config(config)
        self.assertIn("token", str(ctx.exception))

    def test_account_missing_name(self):
        config = {
            "output_path": "/tmp",
            "accounts": [{"token": "ghp_something"}],
        }
        with self.assertRaises(ValueError) as ctx:
            _validate_config(config)
        self.assertIn("name", str(ctx.exception))

    def test_example_placeholder_token_rejected(self):
        config = {
            "output_path": "/tmp",
            "accounts": [{"name": "x", "token": "ghp_xxxxxxxxxxxxxxxxxxxx"}],
        }
        with self.assertRaises(ValueError) as ctx:
            _validate_config(config)
        self.assertIn("placeholder", str(ctx.exception))


class TestLoadConfig(unittest.TestCase):
    def test_load_valid_config_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(VALID_CONFIG, f)
            tmp_path = Path(f.name)

        try:
            config = load_config(tmp_path)
            self.assertEqual(config["output_path"], "/tmp/github-backup-test")
            self.assertEqual(len(config["accounts"]), 1)
            self.assertEqual(config["accounts"][0]["name"], "testuser")
            # Defaults should be applied
            self.assertIn("retry", config)
            self.assertIn("archive", config)
        finally:
            tmp_path.unlink()

    def test_load_invalid_json(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            f.write("not valid json {{{")
            tmp_path = Path(f.name)

        try:
            with self.assertRaises(ValueError) as ctx:
                load_config(tmp_path)
            self.assertIn("not valid JSON", str(ctx.exception))
        finally:
            tmp_path.unlink()

    def test_load_nonexistent_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_config(Path("/nonexistent/path/config.json"))

    def test_comments_stripped_on_load(self):
        config_with_comments = {
            "_comment": "This is the config",
            "output_path": "/tmp",
            "accounts": [
                {"name": "x", "token": "ghp_realtokenwithsufficientlength", "_note": "test"}
            ],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(config_with_comments, f)
            tmp_path = Path(f.name)

        try:
            config = load_config(tmp_path)
            self.assertNotIn("_comment", config)
            self.assertNotIn("_note", config["accounts"][0])
        finally:
            tmp_path.unlink()


class TestGetOutputPath(unittest.TestCase):
    def test_uses_config_path(self):
        config = {"output_path": "/tmp/backups"}
        result = get_output_path(config)
        # resolve() may expand symlinks (e.g., /tmp -> /private/tmp on macOS)
        self.assertTrue(str(result).endswith("/backups"))

    def test_override_takes_precedence(self):
        config = {"output_path": "/tmp/backups"}
        result = get_output_path(config, override="/tmp/override")
        self.assertTrue(str(result).endswith("/override"))

    def test_home_dir_expansion(self):
        config = {"output_path": "~/backups"}
        result = get_output_path(config)
        self.assertNotIn("~", str(result))
        self.assertTrue(str(result).startswith("/"))


if __name__ == "__main__":
    unittest.main()
