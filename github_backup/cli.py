"""
github_backup.cli - Command-line interface and main orchestration.

Entry point: github-backup <command> [options]

Commands:
  run     - Run backup for all (or filtered) accounts
  list    - Dry-run: show what would be backed up
  archive - Create a dated tarball snapshot
  status  - Show last run summary
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="github-backup",
        description="Comprehensive GitHub backup tool - mirrors repos, gists, and metadata.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  github-backup run                        # Backup all configured accounts
  github-backup run --account myuser       # One account only
  github-backup run --org my-org           # One org only
  github-backup run --archive              # Run + create archive snapshot
  github-backup list                       # Preview without making changes
  github-backup archive                    # Create tarball snapshot
  github-backup status                     # Show last run summary
        """,
    )

    # Global options
    parser.add_argument(
        "--config", metavar="PATH",
        help="Path to config file (auto-discovered if not set)",
    )
    parser.add_argument(
        "--output", metavar="PATH",
        help="Override output directory from config",
    )
    parser.add_argument(
        "--account", metavar="NAME",
        help="Limit backup to a specific configured account name",
    )
    parser.add_argument(
        "--org", metavar="NAME",
        help="Limit backup to a specific organization",
    )
    parser.add_argument(
        "--log-level", metavar="LEVEL",
        default="info",
        choices=["debug", "info", "warning", "error"],
        help="Logging verbosity: debug, info, warning, error (default: info)",
    )
    parser.add_argument(
        "--no-color", action="store_true",
        help="Disable colored terminal output",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    # --- run ---
    run_parser = subparsers.add_parser(
        "run",
        help="Run backup for all configured accounts",
    )
    run_parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview actions without making changes (alias for 'list')",
    )
    run_parser.add_argument(
        "--skip-metadata", action="store_true",
        help="Back up git content only, skip issues/PRs/releases/assets",
    )
    run_parser.add_argument(
        "--skip-assets", action="store_true",
        help="Skip downloading release asset binary files",
    )
    run_parser.add_argument(
        "--force", action="store_true",
        help="Ignore resume state, reprocess all items",
    )
    run_parser.add_argument(
        "--archive", action="store_true",
        help="Create a dated archive snapshot after the run completes",
    )

    # --- list ---
    subparsers.add_parser(
        "list",
        help="Dry-run: show all content that would be backed up",
    )

    # --- archive ---
    subparsers.add_parser(
        "archive",
        help="Create a dated tarball snapshot of the backup directory",
    )

    # --- status ---
    subparsers.add_parser(
        "status",
        help="Display summary of the last completed run",
    )

    return parser


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------

def cmd_run(args: argparse.Namespace, config: dict, output_path: Path) -> int:
    """Execute the backup run.

    Args:
        args: Parsed CLI arguments.
        config: Loaded configuration.
        output_path: Resolved output directory.

    Returns:
        Exit code (0 = success, 1 = failures occurred).
    """
    from github_backup.auth import AccountAuth
    from github_backup.discovery import discover_all_with_session
    from github_backup.metadata import (
        save_repo_metadata, save_gist_metadata, save_org_metadata,
    )
    from github_backup.mirror import (
        MirrorError,
        gist_metadata_path,
        gist_mirror_path,
        mirror_repo,
        mirror_wiki,
        org_metadata_path,
        org_repo_metadata_path,
        org_repo_mirror_path,
        repo_metadata_path,
        repo_mirror_path,
        wiki_mirror_path,
    )
    from github_backup.reporter import RunStats, print_summary, save_run_log
    from github_backup.resume import ResumeState
    from github_backup.utils import retry

    output_path.mkdir(parents=True, exist_ok=True)

    # Run flags
    dry_run = getattr(args, "dry_run", False)
    skip_metadata = getattr(args, "skip_metadata", False)
    skip_assets = getattr(args, "skip_assets", False)
    force = getattr(args, "force", False)

    if dry_run:
        logger.info("DRY RUN MODE - no changes will be made")

    # Initialize run tracking
    stats = RunStats()
    resume = ResumeState(output_path, force=force)

    # Retry configuration
    retry_cfg = config.get("retry", {})
    max_attempts = retry_cfg.get("max_attempts", 3)
    backoff = retry_cfg.get("backoff_seconds", 5)

    # Filter accounts if --account flag used
    accounts = config["accounts"]
    if args.account:
        accounts = [a for a in accounts if a["name"] == args.account]
        if not accounts:
            logger.error(
                "No account named '%s' found in config. Available: %s",
                args.account,
                ", ".join(a["name"] for a in config["accounts"]),
            )
            return 1

    proxy_config = config.get("proxy")

    for account_config in accounts:
        account_name = account_config["name"]
        stats.init_account(account_name)

        logger.info("=" * 50)
        logger.info("Processing account: %s", account_name)

        # Set up auth
        try:
            auth = AccountAuth(account_config, proxy_config)
        except Exception as e:
            logger.error("Failed to initialize auth for %s: %s", account_name, e)
            stats.record_failure(account_name, f"Auth failed: {e}")
            continue

        # Discover all content (pass session for API-based org discovery)
        try:
            discovery = discover_all_with_session(
                auth.gh, auth.session, account_config, account_name,
                org_filter=args.org,
            )
        except Exception as e:
            logger.error("Discovery failed for %s: %s", account_name, e)
            stats.record_failure(account_name, f"Discovery failed: {e}")
            continue

        if dry_run:
            print(discovery.summary())
            continue

        # ----------------------------------------------------------------
        # Mirror personal repos + metadata
        # ----------------------------------------------------------------
        for repo in discovery.personal_repos:
            key = resume.repo_key(account_name, repo.full_name)
            if resume.is_done(key):
                logger.debug("Skipping (already done): %s", repo.full_name)
                continue

            dest = repo_mirror_path(output_path, account_name, repo.full_name)
            is_new = not dest.exists()

            # Capture loop variables explicitly to avoid closure bugs
            _clone_url = repo.clone_url
            _html_url = repo.html_url
            _full_name = repo.full_name
            _token = auth.token

            try:
                def _do_mirror(_url=_clone_url, _dest=dest, _tok=_token, _name=_full_name):
                    mirror_repo(_url, _dest, _tok, _name)

                retry(max_attempts=max_attempts, backoff_seconds=backoff)(_do_mirror)()

                # Attempt wiki mirror (non-fatal)
                wiki_dest = wiki_mirror_path(dest)
                mirror_wiki(_html_url, wiki_dest, _token, _full_name)

                # Save metadata
                if not skip_metadata:
                    try:
                        meta_dir = repo_metadata_path(output_path, account_name, _full_name)
                        save_repo_metadata(
                            auth.session, repo, meta_dir,
                            skip_assets=skip_assets,
                        )
                        stats.record_metadata(account_name, success=True)
                    except Exception as me:
                        logger.error("Metadata failed for %s: %s", _full_name, me)
                        stats.record_metadata(account_name, success=False)

                stats.record_repo(account_name, is_new=is_new, success=True)
                resume.mark_complete(key)

            except (MirrorError, Exception) as e:
                err_msg = str(e)
                logger.error("Failed to mirror %s: %s", repo.full_name, err_msg)
                stats.record_repo(account_name, success=False)
                stats.record_failure(repo.full_name, err_msg)

        # ----------------------------------------------------------------
        # Mirror gists + metadata
        # ----------------------------------------------------------------
        for gist in discovery.gists:
            key = resume.gist_key(account_name, gist.id)
            if resume.is_done(key):
                logger.debug("Skipping gist (already done): %s", gist.id)
                continue

            dest = gist_mirror_path(output_path, account_name, gist.id)
            is_new = not dest.exists()

            _pull_url = gist.git_pull_url
            _gist_id = gist.id
            _token = auth.token

            try:
                def _do_gist(_url=_pull_url, _dest=dest, _tok=_token, _id=_gist_id):
                    mirror_repo(_url, _dest, _tok, f"gist:{_id}")

                retry(max_attempts=max_attempts, backoff_seconds=backoff)(_do_gist)()

                # Save gist metadata
                if not skip_metadata:
                    try:
                        meta_dir = gist_metadata_path(output_path, account_name, _gist_id)
                        save_gist_metadata(auth.session, gist, meta_dir)
                    except Exception as me:
                        logger.error("Gist metadata failed for %s: %s", _gist_id, me)

                stats.record_gist(account_name, is_new=is_new, success=True)
                resume.mark_complete(key)

            except (MirrorError, Exception) as e:
                err_msg = str(e)
                logger.error("Failed to mirror gist %s: %s", gist.id, err_msg)
                stats.record_gist(account_name, success=False)
                stats.record_failure(f"gist:{gist.id}", err_msg)

        # ----------------------------------------------------------------
        # Mirror org repos + metadata
        # ----------------------------------------------------------------
        for org_name, org_repos in discovery.orgs.items():
            # Save org-level metadata once per org
            if not skip_metadata:
                try:
                    org_meta = org_metadata_path(output_path, account_name, org_name)
                    _org_obj = auth.gh.get_organization(org_name)
                    save_org_metadata(auth.session, _org_obj, org_meta)
                except Exception as oe:
                    logger.warning("Org metadata failed for %s: %s", org_name, oe)

            for repo in org_repos:
                key = resume.org_repo_key(account_name, org_name, repo.full_name)
                if resume.is_done(key):
                    logger.debug("Skipping org repo (already done): %s", repo.full_name)
                    continue

                dest = org_repo_mirror_path(
                    output_path, account_name, org_name, repo.full_name
                )
                is_new = not dest.exists()

                _clone_url = repo.clone_url
                _html_url = repo.html_url
                _full_name = repo.full_name
                _token = auth.token

                try:
                    def _do_org_mirror(
                        _url=_clone_url, _dest=dest, _tok=_token, _name=_full_name
                    ):
                        mirror_repo(_url, _dest, _tok, _name)

                    retry(max_attempts=max_attempts, backoff_seconds=backoff)(
                        _do_org_mirror
                    )()

                    # Attempt wiki
                    wiki_dest = wiki_mirror_path(dest)
                    mirror_wiki(_html_url, wiki_dest, _token, _full_name)

                    # Save repo metadata
                    if not skip_metadata:
                        try:
                            meta_dir = org_repo_metadata_path(
                                output_path, account_name, org_name, _full_name
                            )
                            save_repo_metadata(
                                auth.session, repo, meta_dir,
                                skip_assets=skip_assets,
                            )
                            stats.record_metadata(account_name, success=True)
                        except Exception as me:
                            logger.error("Metadata failed for %s: %s", _full_name, me)
                            stats.record_metadata(account_name, success=False)

                    stats.record_org_repo(
                        account_name, org_name, is_new=is_new, success=True
                    )
                    resume.mark_complete(key)

                except (MirrorError, Exception) as e:
                    err_msg = str(e)
                    logger.error(
                        "Failed to mirror org repo %s: %s", repo.full_name, err_msg
                    )
                    stats.record_org_repo(account_name, org_name, success=False)
                    stats.record_failure(repo.full_name, err_msg)

    # Finalize
    stats.finish()

    if not dry_run:
        resume.clear()
        save_run_log(stats, output_path)
        print_summary(stats)

        # Create archive if requested via flag or config
        do_archive = getattr(args, "archive", False)
        if not do_archive:
            do_archive = config.get("archive", {}).get("enabled", False)
        if do_archive:
            cmd_archive(args, config, output_path)

    return 1 if stats.total_failures() > 0 else 0


def cmd_list(args: argparse.Namespace, config: dict, output_path: Path) -> int:
    """Dry-run: discover and display all content without making changes.

    Args:
        args: Parsed CLI arguments.
        config: Loaded configuration.
        output_path: Resolved output directory.

    Returns:
        Exit code (always 0).
    """
    from github_backup.auth import AccountAuth
    from github_backup.discovery import discover_all_with_session

    accounts = config["accounts"]
    if args.account:
        accounts = [a for a in accounts if a["name"] == args.account]

    proxy_config = config.get("proxy")

    print("\ngithub-backup dry run - content that would be backed up:\n")

    for account_config in accounts:
        account_name = account_config["name"]
        try:
            auth = AccountAuth(account_config, proxy_config)
            discovery = discover_all_with_session(
                auth.gh, auth.session, account_config, account_name,
                org_filter=args.org,
            )
            print(discovery.summary())
            print()
        except Exception as e:
            logger.error("Failed to discover content for %s: %s", account_name, e)

    return 0


def cmd_archive(args: argparse.Namespace, config: dict, output_path: Path) -> int:
    """Create a dated tarball snapshot of the backup directory.

    Args:
        args: Parsed CLI arguments.
        config: Loaded configuration.
        output_path: Resolved output directory.

    Returns:
        Exit code (0 = success, 1 = failure).
    """
    from github_backup.archive import create_archive, prune_archives

    if not output_path.exists():
        logger.error(
            "Output directory does not exist: %s\n"
            "Run 'github-backup run' first to create a backup.",
            output_path,
        )
        return 1

    archive_dir = output_path / "archives"
    archive_dir.mkdir(parents=True, exist_ok=True)

    try:
        archive_path = create_archive(output_path, archive_dir)
        logger.info("Archive created: %s", archive_path)
        print(f"Archive created: {archive_path}")

        # Apply pruning if configured
        archive_config = config.get("archive", {})
        keep_last = archive_config.get("keep_last")
        keep_days = archive_config.get("keep_days")
        if keep_last or keep_days:
            removed = prune_archives(
                archive_dir, keep_last=keep_last, keep_days=keep_days
            )
            if removed:
                logger.info("Pruned %d old archive(s)", len(removed))

        return 0
    except Exception as e:
        logger.error("Archive creation failed: %s", e)
        return 1


def cmd_status(args: argparse.Namespace, config: dict, output_path: Path) -> int:
    """Display the last run summary from logs/last-run.json.

    Args:
        args: Parsed CLI arguments.
        config: Loaded configuration.
        output_path: Resolved output directory.

    Returns:
        Exit code (0 = success, 1 = no log found).
    """
    log_file = output_path / "logs" / "last-run.json"

    if not log_file.exists():
        print(f"No run log found at: {log_file}")
        print("Run 'github-backup run' to create a backup first.")
        return 1

    try:
        data = json.loads(log_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Could not read run log: %s", e)
        return 1

    from github_backup.utils import format_duration

    duration = format_duration(data.get("duration_seconds", 0))
    print(f"\nLast run: {data.get('started_at', 'unknown')}")
    print(f"Duration: {duration}")
    print(f"Repos:    {data.get('total_repos', 0)}")
    print(f"Failures: {data.get('total_failures', 0)}")

    failures = data.get("failures", [])
    if failures:
        print(f"\nFailures ({len(failures)}):")
        for f in failures:
            print(f"  [ERROR] {f.get('item', '?')}: {f.get('error', '?')}")

    return 0


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Main entry point for the github-backup CLI."""
    parser = build_parser()
    args = parser.parse_args()

    # Default command is 'run' if nothing specified
    if args.command is None:
        args.command = "run"

    # Set up logging first
    from github_backup.utils import setup_logging
    setup_logging(
        level=args.log_level,
        no_color=args.no_color,
    )

    # Load config
    from github_backup.config import load_config, discover_config_path, get_output_path
    try:
        config_path = discover_config_path(args.config)
        config = load_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    output_path = get_output_path(config, getattr(args, "output", None))
    logger.debug("Output directory: %s", output_path)

    # Dispatch command
    command_map = {
        "run": cmd_run,
        "list": cmd_list,
        "archive": cmd_archive,
        "status": cmd_status,
    }

    # Handle --dry-run on 'run' as alias for 'list'
    if args.command == "run" and getattr(args, "dry_run", False):
        exit_code = cmd_list(args, config, output_path)
    else:
        handler = command_map.get(args.command)
        if handler is None:
            parser.print_help()
            sys.exit(1)
        exit_code = handler(args, config, output_path)

    sys.exit(exit_code)
