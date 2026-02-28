"""
github_backup.archive - Tarball snapshot creation and pruning.

Creates dated archive snapshots of the backup directory:
  github-backup-<YYYY-MM-DD>T<HH-MM-SS>.tar.gz

Archives exclude the archives/ subdirectory to prevent nesting.
"""

import logging
import tarfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


def create_archive(output_path: Path, archive_dir: Path) -> Path:
    """Create a dated tarball snapshot of the backup directory.

    Archives everything in output_path EXCEPT the archives/ subdirectory
    (to avoid nested archives).

    Archive format: github-backup-<YYYY-MM-DD>T<HH-MM-SS>.tar.gz
    Timestamps are UTC and to-the-minute to support multiple snapshots per day.

    Args:
        output_path: Root backup directory to archive.
        archive_dir: Directory where archives are stored.

    Returns:
        Path to the created archive file.

    Raises:
        OSError: If archive creation fails.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    archive_name = f"github-backup-{timestamp}.tar.gz"
    archive_path = archive_dir / archive_name

    logger.info("Creating archive: %s", archive_path)

    with tarfile.open(archive_path, "w:gz") as tar:
        for item in sorted(output_path.iterdir()):
            # Skip the archives directory to prevent nesting
            if item.name == "archives":
                continue
            # Skip CLIO internal files
            if item.name == ".clio":
                continue
            # Skip run state file (transient)
            if item.name == ".run-state.json":
                continue

            logger.debug("Archiving: %s", item.name)
            tar.add(item, arcname=item.name, recursive=True)

    size_mb = archive_path.stat().st_size / (1024 * 1024)
    logger.info("Archive created: %s (%.1f MB)", archive_path.name, size_mb)
    return archive_path


def prune_archives(
    archive_dir: Path,
    keep_last: Optional[int] = None,
    keep_days: Optional[int] = None,
) -> List[Path]:
    """Remove old archive files based on keep_last and/or keep_days rules.

    Both rules are applied if set. An archive is removed if it violates
    either rule.

    Args:
        archive_dir: Directory containing archive files.
        keep_last: Keep only the N most recent archives (None = unlimited).
        keep_days: Remove archives older than N days (None = unlimited).

    Returns:
        List of removed archive paths.
    """
    if keep_last is None and keep_days is None:
        return []

    # Find all archives sorted by modification time (newest first)
    archives = sorted(
        archive_dir.glob("github-backup-*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    to_remove = set()

    # keep_last: remove archives beyond the Nth most recent
    if keep_last is not None and len(archives) > keep_last:
        for old in archives[keep_last:]:
            to_remove.add(old)

    # keep_days: remove archives older than N days
    if keep_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
        for archive in archives:
            mtime = datetime.fromtimestamp(archive.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                to_remove.add(archive)

    removed = []
    for archive in to_remove:
        try:
            archive.unlink()
            removed.append(archive)
            logger.info("Pruned old archive: %s", archive.name)
        except OSError as e:
            logger.warning("Could not remove archive %s: %s", archive.name, e)

    return removed


def list_archives(archive_dir: Path) -> List[Path]:
    """List all archives in the archive directory.

    Args:
        archive_dir: Directory containing archive files.

    Returns:
        List of archive paths sorted by modification time (newest first).
    """
    if not archive_dir.exists():
        return []
    return sorted(
        archive_dir.glob("github-backup-*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
