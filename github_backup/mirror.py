"""
github_backup.mirror - Git bare mirror clone and fetch operations.

Handles:
  - Initial mirror clone: git clone --mirror
  - Incremental update: git fetch --all --prune
  - Wiki mirror support
  - Token-in-URL authentication (in-memory only, never persisted)
"""

import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class MirrorError(Exception):
    """Raised when a git mirror operation fails."""
    pass


def _run_git(args: list, description: str) -> subprocess.CompletedProcess:
    """Run a git command, raising MirrorError on failure.

    Args:
        args: Full git command as a list (e.g., ["git", "clone", "--mirror", ...])
        description: Human-readable description for error messages (must not contain token).

    Returns:
        CompletedProcess result.

    Raises:
        MirrorError: If the command exits non-zero.
    """
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Log stderr but only the description (args may contain token)
        stderr = result.stderr.strip()
        # Redact any token-like strings in stderr for safety
        stderr = _redact_tokens(stderr)
        raise MirrorError(f"{description} failed (exit {result.returncode}): {stderr}")
    return result


def _redact_tokens(text: str) -> str:
    """Redact GitHub PAT tokens from git output.

    Looks for ghp_ and gho_ prefixed strings and replaces with ***.

    Args:
        text: Raw git output string.

    Returns:
        String with tokens redacted.
    """
    import re
    return re.sub(r"gh[pos]_[A-Za-z0-9]+", "***", text)


def mirror_clone(
    clone_url: str,
    dest: Path,
    auth_token: str,
    description: str = "mirror clone",
) -> None:
    """Perform an initial bare mirror clone of a repository.

    Creates a bare .git directory at dest that mirrors all refs (branches,
    tags, pull request refs).

    Args:
        clone_url: HTTPS clone URL (plain, without token).
        dest: Destination path for the bare clone (should end in .git).
        auth_token: GitHub PAT used for authentication (embedded in URL in-memory).
        description: Human-readable label for logging (safe, no token).

    Raises:
        MirrorError: If the clone fails.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Embed token in URL for authentication - never written to disk
    auth_url = _embed_token(clone_url, auth_token)

    logger.info("Cloning (mirror): %s -> %s", description, dest)
    _run_git(
        ["git", "clone", "--mirror", auth_url, str(dest)],
        description=f"clone {description}",
    )
    logger.debug("Clone complete: %s", dest)


def mirror_fetch(
    dest: Path,
    clone_url: str,
    auth_token: str,
    description: str = "mirror fetch",
) -> None:
    """Fetch all updates into an existing bare mirror clone.

    Updates the remote URL with the current token (tokens may rotate),
    then fetches all branches and tags, pruning deleted refs.

    Args:
        dest: Path to the existing bare clone directory.
        clone_url: HTTPS clone URL (plain, without token).
        auth_token: GitHub PAT for authentication.
        description: Human-readable label for logging.

    Raises:
        MirrorError: If the fetch fails.
    """
    auth_url = _embed_token(clone_url, auth_token)

    # Update remote URL with current token (handles token rotation)
    logger.debug("Updating remote URL for: %s", description)
    _run_git(
        ["git", "-C", str(dest), "remote", "set-url", "origin", auth_url],
        description=f"set-url {description}",
    )

    logger.info("Fetching updates: %s", description)
    _run_git(
        ["git", "-C", str(dest), "fetch", "--all", "--prune", "--prune-tags"],
        description=f"fetch {description}",
    )
    logger.debug("Fetch complete: %s", dest)


def mirror_repo(
    clone_url: str,
    dest: Path,
    auth_token: str,
    description: str,
) -> None:
    """Mirror a repository - clone if new, fetch if existing.

    This is the primary entry point for mirroring any git repository.

    Args:
        clone_url: HTTPS clone URL.
        dest: Destination path for the bare clone.
        auth_token: GitHub PAT.
        description: Human-readable label (e.g., "owner/repo").

    Raises:
        MirrorError: If either clone or fetch fails.
    """
    if dest.exists():
        # Validate it looks like a bare git repo
        if (dest / "HEAD").exists():
            mirror_fetch(dest, clone_url, auth_token, description)
        else:
            logger.warning(
                "Destination exists but doesn't look like a git repo: %s. Re-cloning.",
                dest,
            )
            import shutil
            shutil.rmtree(dest)
            mirror_clone(clone_url, dest, auth_token, description)
    else:
        mirror_clone(clone_url, dest, auth_token, description)


def mirror_wiki(
    repo_html_url: str,
    dest: Path,
    auth_token: str,
    description: str,
) -> bool:
    """Attempt to mirror a repository's wiki.

    Wikis use a separate .wiki.git URL derived from the repo's URL.
    Not all repos have wikis, so 404s are silently ignored.

    Args:
        repo_html_url: The repo's HTML URL (e.g., https://github.com/owner/repo).
        dest: Destination path for the wiki bare clone.
        auth_token: GitHub PAT.
        description: Human-readable label for logging.

    Returns:
        True if wiki was mirrored, False if wiki doesn't exist.
    """
    # Wiki clone URL: https://github.com/owner/repo.wiki.git
    wiki_url = repo_html_url.rstrip("/") + ".wiki.git"

    try:
        mirror_repo(wiki_url, dest, auth_token, f"{description} (wiki)")
        return True
    except MirrorError as e:
        error_str = str(e)
        # Wiki doesn't exist - common for repos without wikis
        if any(indicator in error_str.lower() for indicator in [
            "repository not found",
            "empty repository",
            "does not exist",
            "not found",
            "remote: repository",
        ]):
            logger.debug("No wiki for: %s", description)
            return False
        # Other error - log but don't fail the parent repo backup
        logger.warning("Wiki mirror failed for %s: %s", description, e)
        return False


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def repo_mirror_path(base_path: Path, account_name: str, repo_full_name: str) -> Path:
    """Build the path for a personal repo's bare clone.

    Args:
        base_path: Output root directory.
        account_name: Account name from config.
        repo_full_name: GitHub full name (owner/repo).

    Returns:
        Path like <base>/accounts/<account>/repos/<repo>.git
    """
    # Use just the repo name (not full owner/name) to keep paths clean
    repo_name = repo_full_name.split("/")[-1]
    return base_path / "accounts" / account_name / "repos" / f"{repo_name}.git"


def gist_mirror_path(base_path: Path, account_name: str, gist_id: str) -> Path:
    """Build the path for a gist's bare clone.

    Args:
        base_path: Output root directory.
        account_name: Account name from config.
        gist_id: GitHub gist ID.

    Returns:
        Path like <base>/accounts/<account>/gists/<gist_id>.git
    """
    return base_path / "accounts" / account_name / "gists" / f"{gist_id}.git"


def org_repo_mirror_path(
    base_path: Path, account_name: str, org_name: str, repo_full_name: str
) -> Path:
    """Build the path for an org repo's bare clone.

    Args:
        base_path: Output root directory.
        account_name: Account name from config.
        org_name: Organization login.
        repo_full_name: GitHub full name (org/repo).

    Returns:
        Path like <base>/accounts/<account>/orgs/<org>/repos/<repo>.git
    """
    repo_name = repo_full_name.split("/")[-1]
    return (
        base_path / "accounts" / account_name / "orgs" / org_name / "repos"
        / f"{repo_name}.git"
    )


def wiki_mirror_path(repo_mirror: Path) -> Path:
    """Build the wiki mirror path adjacent to the repo mirror.

    Args:
        repo_mirror: Path to the repo's bare clone (ending in .git).

    Returns:
        Path like <same dir>/<repo>.wiki.git
    """
    name = repo_mirror.stem  # "reponame" from "reponame.git"
    return repo_mirror.parent / f"{name}.wiki.git"


# ---------------------------------------------------------------------------
# Metadata path helpers
# ---------------------------------------------------------------------------

def repo_metadata_path(base_path: Path, account_name: str, repo_full_name: str) -> Path:
    """Build the metadata directory path for a personal repository.

    Args:
        base_path: Output root directory.
        account_name: Account name from config.
        repo_full_name: GitHub full name (owner/repo).

    Returns:
        Path like <base>/metadata/<account>/repos/<repo>/
    """
    repo_name = repo_full_name.split("/")[-1]
    return base_path / "metadata" / account_name / "repos" / repo_name


def gist_metadata_path(base_path: Path, account_name: str, gist_id: str) -> Path:
    """Build the metadata directory path for a gist.

    Args:
        base_path: Output root directory.
        account_name: Account name from config.
        gist_id: GitHub gist ID.

    Returns:
        Path like <base>/metadata/<account>/gists/<gist_id>/
    """
    return base_path / "metadata" / account_name / "gists" / gist_id


def org_repo_metadata_path(
    base_path: Path, account_name: str, org_name: str, repo_full_name: str
) -> Path:
    """Build the metadata directory path for an organization repository.

    Args:
        base_path: Output root directory.
        account_name: Account name from config.
        org_name: Organization login.
        repo_full_name: GitHub full name (org/repo).

    Returns:
        Path like <base>/metadata/<account>/orgs/<org>/repos/<repo>/
    """
    repo_name = repo_full_name.split("/")[-1]
    return (
        base_path / "metadata" / account_name / "orgs" / org_name / "repos" / repo_name
    )


def org_metadata_path(base_path: Path, account_name: str, org_name: str) -> Path:
    """Build the metadata directory path for an organization.

    Args:
        base_path: Output root directory.
        account_name: Account name from config.
        org_name: Organization login.

    Returns:
        Path like <base>/metadata/<account>/orgs/<org>/
    """
    return base_path / "metadata" / account_name / "orgs" / org_name

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _embed_token(clone_url: str, token: str) -> str:
    """Embed a PAT into an HTTPS URL for git authentication.

    The token is used in-memory only - never persisted to disk.

    Args:
        clone_url: Plain HTTPS clone URL.
        token: GitHub Personal Access Token.

    Returns:
        Authenticated HTTPS URL.
    """
    if clone_url.startswith("https://"):
        return clone_url.replace("https://", f"https://x-token:{token}@", 1)
    return clone_url
