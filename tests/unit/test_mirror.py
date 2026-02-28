"""Unit tests for github_backup.mirror path helpers."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from github_backup.mirror import (
    _embed_token,
    _redact_tokens,
    repo_mirror_path,
    gist_mirror_path,
    org_repo_mirror_path,
    wiki_mirror_path,
    repo_metadata_path,
    gist_metadata_path,
    org_repo_metadata_path,
    org_metadata_path,
)


BASE = Path("/backups")


class TestEmbedToken(unittest.TestCase):
    def test_embeds_token_in_https_url(self):
        url = "https://github.com/owner/repo.git"
        token = "ghp_testtoken123"
        result = _embed_token(url, token)
        self.assertEqual(result, "https://x-token:ghp_testtoken123@github.com/owner/repo.git")

    def test_non_https_url_unchanged(self):
        url = "git@github.com:owner/repo.git"
        token = "ghp_testtoken123"
        result = _embed_token(url, token)
        self.assertEqual(result, url)

    def test_plain_https_url_gets_token(self):
        """Plain HTTPS URLs (no existing auth) should get token embedded."""
        url = "https://github.com/org/private-repo.git"
        token = "ghp_abcdef"
        result = _embed_token(url, token)
        self.assertTrue(result.startswith("https://x-token:ghp_abcdef@"))
        self.assertIn("github.com/org/private-repo.git", result)


class TestRedactTokens(unittest.TestCase):
    def test_redacts_ghp_token(self):
        text = "error: https://x-token:ghp_abcdefghijklmnop@github.com"
        result = _redact_tokens(text)
        self.assertNotIn("ghp_abcdefghijklmnop", result)
        self.assertIn("***", result)

    def test_no_change_without_token(self):
        text = "fatal: repository not found"
        result = _redact_tokens(text)
        self.assertEqual(result, text)


class TestMirrorPaths(unittest.TestCase):
    def test_repo_mirror_path(self):
        result = repo_mirror_path(BASE, "myuser", "myuser/myrepo")
        expected = BASE / "accounts" / "myuser" / "repos" / "myrepo.git"
        self.assertEqual(result, expected)

    def test_repo_mirror_path_strips_owner(self):
        """Only the repo name (not owner/repo) should be used in the path."""
        result = repo_mirror_path(BASE, "acct", "owner/repo-name")
        self.assertEqual(result.name, "repo-name.git")

    def test_gist_mirror_path(self):
        result = gist_mirror_path(BASE, "myuser", "abc123")
        expected = BASE / "accounts" / "myuser" / "gists" / "abc123.git"
        self.assertEqual(result, expected)

    def test_org_repo_mirror_path(self):
        result = org_repo_mirror_path(BASE, "myuser", "my-org", "my-org/repo")
        expected = BASE / "accounts" / "myuser" / "orgs" / "my-org" / "repos" / "repo.git"
        self.assertEqual(result, expected)

    def test_wiki_mirror_path(self):
        repo_path = BASE / "accounts" / "user" / "repos" / "myrepo.git"
        result = wiki_mirror_path(repo_path)
        expected = BASE / "accounts" / "user" / "repos" / "myrepo.wiki.git"
        self.assertEqual(result, expected)


class TestMetadataPaths(unittest.TestCase):
    def test_repo_metadata_path(self):
        result = repo_metadata_path(BASE, "myuser", "myuser/myrepo")
        expected = BASE / "metadata" / "myuser" / "repos" / "myrepo"
        self.assertEqual(result, expected)

    def test_gist_metadata_path(self):
        result = gist_metadata_path(BASE, "myuser", "abc123")
        expected = BASE / "metadata" / "myuser" / "gists" / "abc123"
        self.assertEqual(result, expected)

    def test_org_repo_metadata_path(self):
        result = org_repo_metadata_path(BASE, "myuser", "my-org", "my-org/repo")
        expected = (
            BASE / "metadata" / "myuser" / "orgs" / "my-org" / "repos" / "repo"
        )
        self.assertEqual(result, expected)

    def test_org_metadata_path(self):
        result = org_metadata_path(BASE, "myuser", "my-org")
        expected = BASE / "metadata" / "myuser" / "orgs" / "my-org"
        self.assertEqual(result, expected)

    def test_mirror_and_metadata_paths_are_different(self):
        """Mirror paths and metadata paths should be distinct."""
        mirror = repo_mirror_path(BASE, "user", "user/repo")
        meta = repo_metadata_path(BASE, "user", "user/repo")
        self.assertNotEqual(mirror, meta)
        # Mirror is under accounts/, metadata is under metadata/
        self.assertIn("accounts", str(mirror))
        self.assertIn("metadata", str(meta))


if __name__ == "__main__":
    unittest.main()
