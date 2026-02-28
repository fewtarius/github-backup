"""Unit tests for github_backup.resume."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from github_backup.resume import ResumeState


class TestResumeState(unittest.TestCase):
    def setUp(self):
        """Create a temporary directory for each test."""
        self.tmpdir = tempfile.mkdtemp()
        self.output_path = Path(self.tmpdir)

    def tearDown(self):
        """Clean up temp files."""
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_fresh_state_is_empty(self):
        """New state should have no completed items."""
        state = ResumeState(self.output_path)
        self.assertEqual(len(state.completed), 0)

    def test_state_file_created(self):
        """State file should be created on initialization."""
        ResumeState(self.output_path)
        state_file = self.output_path / ".run-state.json"
        self.assertTrue(state_file.exists())

    def test_mark_complete_persists(self):
        """Marking complete should persist to disk."""
        state = ResumeState(self.output_path)
        key = "account:myuser:repo:owner/repo"
        state.mark_complete(key)

        # Read state file directly to verify persistence
        data = json.loads(
            (self.output_path / ".run-state.json").read_text(encoding="utf-8")
        )
        self.assertIn(key, data["completed"])

    def test_is_done_returns_true_for_completed(self):
        """is_done should return True for marked-complete items."""
        state = ResumeState(self.output_path)
        key = "account:myuser:gist:abc123"
        self.assertFalse(state.is_done(key))
        state.mark_complete(key)
        self.assertTrue(state.is_done(key))

    def test_resume_loads_existing_state(self):
        """New ResumeState should load existing state file."""
        # Create initial state
        state1 = ResumeState(self.output_path)
        key = "account:myuser:repo:owner/repo"
        state1.mark_complete(key)

        # Create new state object (simulates restart)
        state2 = ResumeState(self.output_path)
        self.assertTrue(state2.is_done(key))

    def test_force_ignores_existing_state(self):
        """--force flag should start fresh even if state file exists."""
        state1 = ResumeState(self.output_path)
        key = "account:myuser:repo:owner/repo"
        state1.mark_complete(key)

        # Force new state
        state2 = ResumeState(self.output_path, force=True)
        self.assertFalse(state2.is_done(key))

    def test_clear_removes_state_file(self):
        """clear() should remove the state file."""
        state = ResumeState(self.output_path)
        state_file = self.output_path / ".run-state.json"
        self.assertTrue(state_file.exists())

        state.clear()
        self.assertFalse(state_file.exists())

    def test_clear_idempotent(self):
        """clear() should not raise if file already gone."""
        state = ResumeState(self.output_path)
        state.clear()
        state.clear()  # Should not raise

    def test_repo_key_format(self):
        key = ResumeState.repo_key("myuser", "owner/repo")
        self.assertEqual(key, "account:myuser:repo:owner/repo")

    def test_gist_key_format(self):
        key = ResumeState.gist_key("myuser", "abc123def456")
        self.assertEqual(key, "account:myuser:gist:abc123def456")

    def test_org_repo_key_format(self):
        key = ResumeState.org_repo_key("myuser", "my-org", "my-org/repo")
        self.assertEqual(key, "account:myuser:org:my-org:repo:my-org/repo")

    def test_metadata_key_format(self):
        key = ResumeState.metadata_key("myuser", "owner/repo")
        self.assertEqual(key, "account:myuser:meta:owner/repo")

    def test_corrupted_state_file_starts_fresh(self):
        """Corrupted state file should be silently ignored."""
        state_file = self.output_path / ".run-state.json"
        state_file.write_text("not valid json {{", encoding="utf-8")

        # Should not raise, should start fresh
        state = ResumeState(self.output_path)
        self.assertEqual(len(state.completed), 0)


class TestResumeStatePaths(unittest.TestCase):
    """Verify key builder static methods produce consistent output."""

    def test_all_key_builders_are_unique(self):
        """Same item but different types should produce different keys."""
        keys = {
            ResumeState.repo_key("user", "user/repo"),
            ResumeState.gist_key("user", "repo"),
            ResumeState.org_repo_key("user", "org", "org/repo"),
            ResumeState.metadata_key("user", "user/repo"),
        }
        # All 4 should be distinct
        self.assertEqual(len(keys), 4)

    def test_different_accounts_produce_different_keys(self):
        """Same repo for different accounts must have different keys."""
        key1 = ResumeState.repo_key("account1", "owner/repo")
        key2 = ResumeState.repo_key("account2", "owner/repo")
        self.assertNotEqual(key1, key2)


if __name__ == "__main__":
    unittest.main()
