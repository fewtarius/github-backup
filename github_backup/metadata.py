"""
github_backup.metadata - Fetch and save non-git GitHub content.

Handles:
  - Repository metadata (description, topics, settings)
  - Issues and issue comments (all, open + closed)
  - Pull requests, reviews, and comments (all)
  - Releases metadata
  - Release asset binary downloads
  - Organization metadata
  - Gist metadata

All data is saved as pretty-printed JSON with atomic writes.
Paginated API responses are fully consumed (no truncation).
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

from github_backup.utils import get_all_pages, handle_rate_limit

logger = logging.getLogger(__name__)

# GitHub API base URL
_API_BASE = "https://api.github.com"


# ---------------------------------------------------------------------------
# Atomic JSON write helper
# ---------------------------------------------------------------------------

def _write_json(path: Path, data) -> None:
    """Write data as pretty-printed JSON using an atomic write.

    Args:
        path: Destination file path.
        data: Data to serialize (dict, list, etc.)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    tmp.rename(path)


# ---------------------------------------------------------------------------
# Repository metadata
# ---------------------------------------------------------------------------

def save_repo_metadata(
    session,
    repo,
    metadata_dir: Path,
    skip_assets: bool = False,
) -> None:
    """Fetch and save all metadata for a repository.

    Saves:
      - repo.json (repository information and topics)
      - issues.json (all issues + comments)
      - pull_requests.json (all PRs + reviews + comments)
      - releases.json (all releases)
      - assets/ (release asset binary files, unless skip_assets=True)

    Args:
        session: Authenticated requests.Session.
        repo: PyGitHub Repository object.
        metadata_dir: Directory to save metadata files.
        skip_assets: If True, skip downloading binary release assets.
    """
    metadata_dir.mkdir(parents=True, exist_ok=True)
    full_name = repo.full_name
    logger.info("Fetching metadata for: %s", full_name)

    # Basic repo info
    _save_repo_info(session, repo, metadata_dir)

    # Issues (includes comments)
    _save_issues(session, full_name, metadata_dir)

    # Pull requests (includes reviews and comments)
    _save_pull_requests(session, full_name, metadata_dir)

    # Releases (and optionally assets)
    _save_releases(session, full_name, metadata_dir, skip_assets=skip_assets)

    logger.info("Metadata complete: %s", full_name)


def _save_repo_info(session, repo, metadata_dir: Path) -> None:
    """Save basic repository information.

    Args:
        session: Authenticated requests.Session.
        repo: PyGitHub Repository object.
        metadata_dir: Destination directory.
    """
    try:
        topics = repo.get_topics()
    except Exception:
        topics = []

    repo_data = {
        "id": repo.id,
        "full_name": repo.full_name,
        "name": repo.name,
        "description": repo.description,
        "html_url": repo.html_url,
        "clone_url": repo.clone_url,
        "ssh_url": repo.ssh_url,
        "private": repo.private,
        "fork": repo.fork,
        "archived": repo.archived,
        "disabled": getattr(repo, "disabled", repo.archived),
        "language": repo.language,
        "topics": topics,
        "stargazers_count": repo.stargazers_count,
        "watchers_count": repo.watchers_count,
        "forks_count": repo.forks_count,
        "open_issues_count": repo.open_issues_count,
        "default_branch": repo.default_branch,
        "has_issues": repo.has_issues,
        "has_wiki": repo.has_wiki,
        "has_projects": repo.has_projects,
        "has_downloads": repo.has_downloads,
        "license": repo.license.spdx_id if repo.license else None,
        "created_at": str(repo.created_at),
        "updated_at": str(repo.updated_at),
        "pushed_at": str(repo.pushed_at),
    }

    _write_json(metadata_dir / "repo.json", repo_data)
    logger.debug("Saved repo info: %s", repo.full_name)


def _save_issues(session, full_name: str, metadata_dir: Path) -> None:
    """Fetch all issues and their comments.

    Fetches both open and closed issues. Comments are embedded
    within each issue object.

    Args:
        session: Authenticated requests.Session.
        full_name: Repository full name (owner/repo).
        metadata_dir: Destination directory.
    """
    logger.debug("Fetching issues for: %s", full_name)

    url = f"{_API_BASE}/repos/{full_name}/issues"
    params = {
        "state": "all",
        "per_page": 100,
        "direction": "asc",
    }

    try:
        issues = get_all_pages(session, url, params=params)
    except Exception as e:
        logger.error("Failed to fetch issues for %s: %s", full_name, e)
        return

    # Enrich each issue with its comments
    enriched = []
    for issue in issues:
        issue_number = issue.get("number")
        comments_url = issue.get("comments_url")

        # Fetch comments if any exist
        if issue.get("comments", 0) > 0 and comments_url:
            try:
                comments = get_all_pages(session, comments_url)
                issue["_comments"] = comments
            except Exception as e:
                logger.warning(
                    "Failed to fetch comments for %s#%s: %s",
                    full_name, issue_number, e,
                )
                issue["_comments"] = []
        else:
            issue["_comments"] = []

        enriched.append(issue)

    _write_json(metadata_dir / "issues.json", enriched)
    logger.debug("Saved %d issues for: %s", len(enriched), full_name)


def _save_pull_requests(session, full_name: str, metadata_dir: Path) -> None:
    """Fetch all pull requests with reviews and comments.

    Args:
        session: Authenticated requests.Session.
        full_name: Repository full name (owner/repo).
        metadata_dir: Destination directory.
    """
    logger.debug("Fetching pull requests for: %s", full_name)

    url = f"{_API_BASE}/repos/{full_name}/pulls"
    params = {
        "state": "all",
        "per_page": 100,
        "direction": "asc",
    }

    try:
        prs = get_all_pages(session, url, params=params)
    except Exception as e:
        logger.error("Failed to fetch PRs for %s: %s", full_name, e)
        return

    enriched = []
    for pr in prs:
        pr_number = pr.get("number")

        # Fetch review comments (line-level comments)
        review_comments_url = pr.get("review_comments_url")
        if pr.get("review_comments", 0) > 0 and review_comments_url:
            try:
                pr["_review_comments"] = get_all_pages(session, review_comments_url)
            except Exception as e:
                logger.warning("Failed to fetch review comments for %s#%s: %s",
                               full_name, pr_number, e)
                pr["_review_comments"] = []
        else:
            pr["_review_comments"] = []

        # Fetch reviews (approve/request changes/comment)
        reviews_url = f"{_API_BASE}/repos/{full_name}/pulls/{pr_number}/reviews"
        try:
            pr["_reviews"] = get_all_pages(session, reviews_url)
        except Exception as e:
            logger.warning("Failed to fetch reviews for %s#%s: %s",
                           full_name, pr_number, e)
            pr["_reviews"] = []

        # Fetch issue-level comments (regular PR comments, not line comments)
        comments_url = pr.get("comments_url")
        if pr.get("comments", 0) > 0 and comments_url:
            try:
                pr["_comments"] = get_all_pages(session, comments_url)
            except Exception as e:
                logger.warning("Failed to fetch PR comments for %s#%s: %s",
                               full_name, pr_number, e)
                pr["_comments"] = []
        else:
            pr["_comments"] = []

        enriched.append(pr)

    _write_json(metadata_dir / "pull_requests.json", enriched)
    logger.debug("Saved %d PRs for: %s", len(enriched), full_name)


def _save_releases(
    session,
    full_name: str,
    metadata_dir: Path,
    skip_assets: bool = False,
) -> None:
    """Fetch all releases and optionally download release assets.

    Args:
        session: Authenticated requests.Session.
        full_name: Repository full name (owner/repo).
        metadata_dir: Destination directory.
        skip_assets: If True, skip downloading binary asset files.
    """
    logger.debug("Fetching releases for: %s", full_name)

    url = f"{_API_BASE}/repos/{full_name}/releases"
    params = {"per_page": 100}

    try:
        releases = get_all_pages(session, url, params=params)
    except Exception as e:
        logger.error("Failed to fetch releases for %s: %s", full_name, e)
        return

    _write_json(metadata_dir / "releases.json", releases)
    logger.debug("Saved %d releases for: %s", len(releases), full_name)

    # Download assets
    if not skip_assets and releases:
        assets_dir = metadata_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        _download_assets(session, full_name, releases, assets_dir)


def _download_assets(session, full_name: str, releases: list, assets_dir: Path) -> None:
    """Download all release asset binary files.

    Args:
        session: Authenticated requests.Session.
        full_name: Repository full name (for logging).
        releases: List of release data dicts.
        assets_dir: Directory to store downloaded assets.
    """
    total_assets = sum(len(r.get("assets", [])) for r in releases)
    if total_assets == 0:
        return

    logger.info("Downloading %d release assets for: %s", total_assets, full_name)
    downloaded = 0
    skipped = 0

    for release in releases:
        tag = release.get("tag_name", "unknown")
        release_dir = assets_dir / tag
        release_dir.mkdir(parents=True, exist_ok=True)

        for asset in release.get("assets", []):
            asset_name = asset.get("name", "unknown")
            asset_path = release_dir / asset_name
            asset_url = asset.get("url")  # API URL (not browser download URL)
            expected_size = asset.get("size", 0)

            # Skip if already downloaded and size matches
            if asset_path.exists() and asset_path.stat().st_size == expected_size:
                logger.debug("Asset already current: %s/%s", tag, asset_name)
                skipped += 1
                continue

            try:
                # Use Accept header for binary download
                resp = session.get(
                    asset_url,
                    headers={"Accept": "application/octet-stream"},
                    stream=True,
                )
                resp.raise_for_status()
                handle_rate_limit(resp)

                # Stream to disk
                tmp_path = asset_path.with_suffix(asset_path.suffix + ".tmp")
                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                tmp_path.rename(asset_path)

                downloaded += 1
                logger.debug("Downloaded asset: %s/%s", tag, asset_name)

            except Exception as e:
                logger.warning(
                    "Failed to download asset %s/%s: %s", tag, asset_name, e
                )

    logger.info(
        "Assets for %s: %d downloaded, %d already current",
        full_name, downloaded, skipped,
    )


# ---------------------------------------------------------------------------
# Gist metadata
# ---------------------------------------------------------------------------

def save_gist_metadata(session, gist, metadata_dir: Path) -> None:
    """Fetch and save metadata for a gist.

    Args:
        session: Authenticated requests.Session.
        gist: PyGitHub Gist object.
        metadata_dir: Directory to save metadata.
    """
    metadata_dir.mkdir(parents=True, exist_ok=True)

    # Fetch full gist detail via API for complete data
    try:
        resp = session.get(f"{_API_BASE}/gists/{gist.id}")
        resp.raise_for_status()
        handle_rate_limit(resp)
        gist_data = resp.json()
    except Exception as e:
        logger.warning("Could not fetch full gist detail for %s: %s", gist.id, e)
        # Fall back to PyGitHub object data
        gist_data = {
            "id": gist.id,
            "description": gist.description,
            "public": gist.public,
            "html_url": gist.html_url,
            "git_pull_url": gist.git_pull_url,
            "created_at": str(gist.created_at),
            "updated_at": str(gist.updated_at),
            "files": {
                name: {
                    "filename": f.filename,
                    "type": f.type,
                    "size": f.size,
                }
                for name, f in gist.files.items()
            },
        }

    _write_json(metadata_dir / "gist.json", gist_data)
    logger.debug("Saved gist metadata: %s", gist.id)


# ---------------------------------------------------------------------------
# Organization metadata
# ---------------------------------------------------------------------------

def save_org_metadata(session, org, metadata_dir: Path) -> None:
    """Fetch and save organization metadata.

    Args:
        session: Authenticated requests.Session.
        org: PyGitHub Organization object.
        metadata_dir: Directory to save metadata.
    """
    metadata_dir.mkdir(parents=True, exist_ok=True)

    try:
        resp = session.get(f"{_API_BASE}/orgs/{org.login}")
        resp.raise_for_status()
        handle_rate_limit(resp)
        org_data = resp.json()
    except Exception as e:
        logger.warning("Could not fetch full org detail for %s: %s", org.login, e)
        org_data = {
            "login": org.login,
            "name": org.name,
            "description": org.description,
            "html_url": org.html_url,
            "public_repos": org.public_repos,
            "created_at": str(org.created_at),
        }

    _write_json(metadata_dir / "org.json", org_data)
    logger.debug("Saved org metadata: %s", org.login)
