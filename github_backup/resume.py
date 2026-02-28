"""
github_backup.resume - Run state tracking for resumable backup runs.

Tracks which repos/gists have been successfully processed in the current run.
If a run is interrupted, restarting will skip already-completed items.

State file location: <output_path>/.run-state.json

State file format:
{
    "run_started": "2026-02-24T14:30:00",
    "completed": [
        "account:myuser:repo:owner/reponame",
        "account:myuser:gist:gist_id",
        "account:myuser:org:orgname:repo:owner/reponame"
    ]
}

Key format:
    Personal repo:  "account:{name}:repo:{owner}/{repo}"
    Gist:           "account:{name}:gist:{gist_id}"
    Org repo:       "account:{name}:org:{org}:repo:{owner}/{repo}"
    Metadata item:  "account:{name}:meta:{owner}/{repo}"
"""

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Set

logger = logging.getLogger(__name__)

_STATE_FILENAME = ".run-state.json"


class ResumeState:
    """Tracks completion state for a backup run.

    Thread-safe for single-process use (no locking needed for sequential ops).
    Uses atomic writes to prevent corruption on interrupt.

    Attributes:
        state_file: Path to the state JSON file.
        run_started: ISO timestamp when this run began.
        completed: Set of completion keys for this run.
    """

    def __init__(self, output_path: Path, force: bool = False):
        """Initialize resume state.

        Args:
            output_path: Backup output directory (state file stored here).
            force: If True, ignore existing state and start fresh.
        """
        self.state_file = output_path / _STATE_FILENAME
        self.completed: Set[str] = set()
        self.run_started: str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        if not force and self.state_file.exists():
            self._load()
        else:
            if force and self.state_file.exists():
                logger.info("--force flag set: ignoring existing resume state")
            self._save()  # Create fresh state file

    def _load(self) -> None:
        """Load existing state from disk."""
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            self.run_started = data.get("run_started", self.run_started)
            self.completed = set(data.get("completed", []))
            logger.info(
                "Resuming run started at %s (%d items already completed)",
                self.run_started, len(self.completed),
            )
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning("Could not load resume state (%s), starting fresh", e)
            self.completed = set()

    def _save(self) -> None:
        """Persist current state to disk (atomic write)."""
        data = {
            "run_started": self.run_started,
            "completed": sorted(self.completed),
        }
        # Atomic write: write to temp file then rename
        tmp = self.state_file.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.rename(self.state_file)
        except OSError as e:
            logger.warning("Could not save resume state: %s", e)
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    def is_done(self, key: str) -> bool:
        """Check if an item has already been completed.

        Args:
            key: Completion key (see module docstring for format).

        Returns:
            True if the item was already completed in this run.
        """
        return key in self.completed

    def mark_complete(self, key: str) -> None:
        """Mark an item as completed and persist to disk.

        Args:
            key: Completion key (see module docstring for format).
        """
        self.completed.add(key)
        self._save()

    def clear(self) -> None:
        """Remove the state file on successful run completion."""
        if self.state_file.exists():
            self.state_file.unlink()
            logger.debug("Cleared resume state file")

    # ------------------------------------------------------------------
    # Key builders - consistent key format across the codebase
    # ------------------------------------------------------------------

    @staticmethod
    def repo_key(account_name: str, full_name: str) -> str:
        """Build a key for a personal repository.

        Args:
            account_name: Account name from config.
            full_name: GitHub repo full name (owner/repo).
        """
        return f"account:{account_name}:repo:{full_name}"

    @staticmethod
    def gist_key(account_name: str, gist_id: str) -> str:
        """Build a key for a gist.

        Args:
            account_name: Account name from config.
            gist_id: GitHub gist ID.
        """
        return f"account:{account_name}:gist:{gist_id}"

    @staticmethod
    def org_repo_key(account_name: str, org_name: str, full_name: str) -> str:
        """Build a key for an organization repository.

        Args:
            account_name: Account name from config.
            org_name: Organization login name.
            full_name: GitHub repo full name (org/repo).
        """
        return f"account:{account_name}:org:{org_name}:repo:{full_name}"

    @staticmethod
    def metadata_key(account_name: str, full_name: str) -> str:
        """Build a key for a repository's metadata (issues, PRs, etc.).

        Args:
            account_name: Account name from config.
            full_name: GitHub repo full name.
        """
        return f"account:{account_name}:meta:{full_name}"
