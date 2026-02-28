"""
github_backup.reporter - Run summary reporting.

Generates a human-readable summary at the end of each run and saves
a machine-readable JSON log to <output_path>/logs/last-run.json.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from github_backup.utils import format_duration

logger = logging.getLogger(__name__)


class RunStats:
    """Accumulates statistics across a backup run.

    Attributes:
        started_at: ISO timestamp when the run started.
        finished_at: ISO timestamp when the run completed.
        accounts: Per-account statistics dict.
        failures: List of (item_description, error_message) tuples.
    """

    def __init__(self):
        self.started_at: str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        self.finished_at: Optional[str] = None
        self.accounts: Dict[str, dict] = {}
        self.failures: List[Tuple[str, str]] = []

    def init_account(self, account_name: str) -> None:
        """Initialize stats structure for an account."""
        self.accounts[account_name] = {
            "repos": {"success": 0, "new": 0, "failed": 0},
            "gists": {"success": 0, "new": 0, "failed": 0},
            "orgs": {},
            "metadata": {"success": 0, "failed": 0},
        }

    def record_repo(
        self, account_name: str, is_new: bool = False, success: bool = True
    ) -> None:
        """Record a personal repo backup result."""
        acct = self.accounts.setdefault(account_name, {})
        repos = acct.setdefault("repos", {"success": 0, "new": 0, "failed": 0})
        if success:
            repos["success"] += 1
            if is_new:
                repos["new"] += 1
        else:
            repos["failed"] += 1

    def record_gist(
        self, account_name: str, is_new: bool = False, success: bool = True
    ) -> None:
        """Record a gist backup result."""
        acct = self.accounts.setdefault(account_name, {})
        gists = acct.setdefault("gists", {"success": 0, "new": 0, "failed": 0})
        if success:
            gists["success"] += 1
            if is_new:
                gists["new"] += 1
        else:
            gists["failed"] += 1

    def record_org_repo(
        self,
        account_name: str,
        org_name: str,
        is_new: bool = False,
        success: bool = True,
    ) -> None:
        """Record an org repo backup result."""
        acct = self.accounts.setdefault(account_name, {})
        orgs = acct.setdefault("orgs", {})
        org = orgs.setdefault(org_name, {"success": 0, "new": 0, "failed": 0})
        if success:
            org["success"] += 1
            if is_new:
                org["new"] += 1
        else:
            org["failed"] += 1

    def record_metadata(self, account_name: str, success: bool = True) -> None:
        """Record a metadata fetch result."""
        acct = self.accounts.setdefault(account_name, {})
        meta = acct.setdefault("metadata", {"success": 0, "failed": 0})
        if success:
            meta["success"] += 1
        else:
            meta["failed"] += 1

    def record_failure(self, item: str, error: str) -> None:
        """Record a failure for the failures summary section.

        Args:
            item: Description of what failed (e.g., "org/repo").
            error: Error message (must not contain tokens).
        """
        self.failures.append((item, error))

    def finish(self) -> None:
        """Mark the run as complete."""
        self.finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    def duration_seconds(self) -> float:
        """Calculate run duration in seconds."""
        if not self.finished_at:
            return 0.0
        from datetime import datetime
        fmt = "%Y-%m-%dT%H:%M:%S"
        start = datetime.strptime(self.started_at, fmt)
        end = datetime.strptime(self.finished_at, fmt)
        return (end - start).total_seconds()

    def total_repos(self) -> int:
        """Total repos across all accounts."""
        total = 0
        for acct in self.accounts.values():
            total += acct.get("repos", {}).get("success", 0)
            for org in acct.get("orgs", {}).values():
                total += org.get("success", 0)
        return total

    def total_failures(self) -> int:
        """Total failure count."""
        return len(self.failures)


def print_summary(stats: RunStats) -> None:
    """Print a human-readable run summary to stdout.

    Args:
        stats: Completed RunStats object.
    """
    duration = format_duration(stats.duration_seconds())
    failure_count = stats.total_failures()

    lines = [
        "",
        "=" * 60,
        "  github-backup Run Summary",
        "=" * 60,
        f"  Started:  {stats.started_at}",
        f"  Finished: {stats.finished_at or 'in progress'}",
        f"  Duration: {duration}",
        "",
    ]

    for account_name, acct in stats.accounts.items():
        lines.append(f"  Account: {account_name}")

        repos = acct.get("repos", {})
        lines.append(
            f"    Repositories: {repos.get('success', 0)} updated"
            f", {repos.get('new', 0)} new"
            f", {repos.get('failed', 0)} failed"
        )

        gists = acct.get("gists", {})
        lines.append(
            f"    Gists:        {gists.get('success', 0)} updated"
            f", {gists.get('new', 0)} new"
            f", {gists.get('failed', 0)} failed"
        )

        orgs = acct.get("orgs", {})
        if orgs:
            lines.append(f"    Organizations: {len(orgs)} discovered")
            for org_name, org_stats in orgs.items():
                lines.append(
                    f"      {org_name}: {org_stats.get('success', 0)} updated"
                    f", {org_stats.get('new', 0)} new"
                    f", {org_stats.get('failed', 0)} failed"
                )

        meta = acct.get("metadata", {})
        if meta.get("success", 0) or meta.get("failed", 0):
            lines.append(
                f"    Metadata: {meta.get('success', 0)} completed"
                f", {meta.get('failed', 0)} failed"
            )
        lines.append("")

    if failure_count > 0:
        lines.append(f"  Failures ({failure_count}):")
        for item, error in stats.failures:
            lines.append(f"    [ERROR] {item}")
            lines.append(f"            {error}")
        lines.append("")

    total_msg = f"  Total: {stats.total_repos()} repositories"
    total_gists = sum(
        a.get("gists", {}).get("success", 0) for a in stats.accounts.values()
    )
    if total_gists:
        total_msg += f", {total_gists} gists"
    if failure_count:
        total_msg += f", {failure_count} failures"
    lines.append(total_msg)
    lines.append("=" * 60)

    print("\n".join(lines))


def save_run_log(stats: RunStats, output_path: Path) -> None:
    """Save a machine-readable JSON log of the run.

    Saves to:
    - <output_path>/logs/last-run.json (always overwritten)
    - <output_path>/logs/github-backup-<timestamp>.log (appended)

    Args:
        stats: Completed RunStats object.
        output_path: Backup output directory.
    """
    logs_dir = output_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "started_at": stats.started_at,
        "finished_at": stats.finished_at,
        "duration_seconds": stats.duration_seconds(),
        "total_repos": stats.total_repos(),
        "total_failures": stats.total_failures(),
        "accounts": stats.accounts,
        "failures": [
            {"item": item, "error": error} for item, error in stats.failures
        ],
    }

    # Always-current summary
    last_run = logs_dir / "last-run.json"
    tmp = last_run.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.rename(last_run)

    logger.debug("Run log saved to: %s", last_run)
