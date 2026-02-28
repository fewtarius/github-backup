"""
github_backup.discovery - Enumerate all GitHub content for an account.

Discovers:
  - Personal repositories (including forks, private repos)
  - Gists (public and secret)
  - Organizations the account belongs to
  - All repositories within each organization

Respects account-level include/exclude filters from config.
"""

import logging
from typing import List, Optional

from github import Github, GithubException
from github.Gist import Gist
from github.Organization import Organization
from github.Repository import Repository

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Repository discovery
# ---------------------------------------------------------------------------

def discover_user_repos(gh: Github, account_name: str) -> List[Repository]:
    """Enumerate all repositories owned by the authenticated user.

    Includes private repos and forked repos.

    Args:
        gh: Authenticated PyGitHub client.
        account_name: Account name for logging.

    Returns:
        List of Repository objects.
    """
    repos = []
    user = gh.get_user()
    logger.info("[%s] Discovering personal repositories...", account_name)

    try:
        for repo in user.get_repos(affiliation="owner", sort="full_name"):
            repos.append(repo)
            logger.debug("[%s] Found repo: %s", account_name, repo.full_name)
    except GithubException as e:
        logger.error("[%s] Failed to list repositories: %s", account_name, e)

    logger.info("[%s] Found %d personal repositories", account_name, len(repos))
    return repos


def discover_gists(gh: Github, account_name: str) -> List[Gist]:
    """Enumerate all gists (public and secret) for the authenticated user.

    Args:
        gh: Authenticated PyGitHub client.
        account_name: Account name for logging.

    Returns:
        List of Gist objects.
    """
    gists = []
    user = gh.get_user()
    logger.info("[%s] Discovering gists...", account_name)

    try:
        for gist in user.get_gists():
            gists.append(gist)
            logger.debug("[%s] Found gist: %s", account_name, gist.id)
    except GithubException as e:
        logger.error("[%s] Failed to list gists: %s", account_name, e)

    logger.info("[%s] Found %d gists", account_name, len(gists))
    return gists


# ---------------------------------------------------------------------------
# Organization discovery
# ---------------------------------------------------------------------------

def discover_org_logins(
    gh: Github,
    session,
    account_name: str,
    include_orgs: Optional[List[str]] = None,
    exclude_orgs: Optional[List[str]] = None,
) -> List[str]:
    """Enumerate organization logins the authenticated user belongs to.

    Uses a multi-method strategy for maximum coverage regardless of token type:

    1. /user/orgs REST API (requires read:org scope, returns all memberships)
    2. /users/{login}/orgs REST API (no scope needed, returns public memberships)
    3. PyGitHub user.get_orgs() (fallback)

    Results are deduplicated and merged.

    Args:
        gh: Authenticated PyGitHub client.
        session: Authenticated requests.Session.
        account_name: Account name for logging.
        include_orgs: List of org logins to include, or ["all"] for all orgs.
        exclude_orgs: List of org logins to skip.

    Returns:
        List of org login strings matching the filters.
    """
    from github_backup.utils import get_all_pages

    include_orgs = include_orgs or ["all"]
    exclude_orgs = set(exclude_orgs or [])
    include_all = "all" in include_orgs
    include_set = set(include_orgs) if not include_all else set()

    all_logins = set()

    if session is not None:
        # Method 1: /user/orgs - works with classic PAT + read:org scope
        try:
            orgs1 = get_all_pages(session, "https://api.github.com/user/orgs")
            for o in orgs1:
                login = o.get("login", "")
                if login:
                    all_logins.add(login)
            logger.debug("[%s] /user/orgs found %d orgs", account_name, len(orgs1))
        except Exception as e:
            logger.debug("[%s] /user/orgs failed: %s", account_name, e)

        # Method 2: /users/{login}/orgs - works for public memberships, any token type
        try:
            me_resp = session.get("https://api.github.com/user")
            me_resp.raise_for_status()
            user_login = me_resp.json().get("login", "")
            if user_login:
                orgs2 = get_all_pages(
                    session, f"https://api.github.com/users/{user_login}/orgs"
                )
                for o in orgs2:
                    login = o.get("login", "")
                    if login:
                        all_logins.add(login)
                logger.debug(
                    "[%s] /users/%s/orgs found %d orgs",
                    account_name, user_login, len(orgs2),
                )
        except Exception as e:
            logger.debug("[%s] /users/{login}/orgs failed: %s", account_name, e)

    # Method 3: PyGitHub fallback (often returns same as /user/orgs)
    if not all_logins:
        try:
            user = gh.get_user()
            for org in user.get_orgs():
                all_logins.add(org.login)
            logger.debug("[%s] PyGitHub get_orgs found %d orgs", account_name, len(all_logins))
        except GithubException as e:
            logger.warning("[%s] PyGitHub get_orgs failed: %s", account_name, e)

    # Apply filters
    result = []
    for login in sorted(all_logins):
        if login in exclude_orgs:
            logger.debug("[%s] Skipping excluded org: %s", account_name, login)
            continue
        if not include_all and login not in include_set:
            logger.debug("[%s] Skipping org not in include list: %s", account_name, login)
            continue
        result.append(login)
        logger.debug("[%s] Including org: %s", account_name, login)

    logger.info("[%s] Discovered %d organizations", account_name, len(result))
    return result


def discover_org_repos(
    org: Organization,
    account_name: str,
) -> List[Repository]:
    """Enumerate all repositories in an organization.

    Args:
        org: PyGitHub Organization object.
        account_name: Account name for logging.

    Returns:
        List of Repository objects.
    """
    repos = []
    logger.info("[%s] Discovering repos in org: %s", account_name, org.login)

    try:
        for repo in org.get_repos(sort="full_name"):
            repos.append(repo)
            logger.debug("[%s/%s] Found repo: %s", account_name, org.login, repo.full_name)
    except GithubException as e:
        logger.error(
            "[%s] Failed to list repos for org %s: %s",
            account_name, org.login, e,
        )

    logger.info(
        "[%s] Found %d repos in org: %s",
        account_name, len(repos), org.login,
    )
    return repos


# ---------------------------------------------------------------------------
# Filtering helpers
# ---------------------------------------------------------------------------

def apply_repo_filters(
    repos: List[Repository],
    include_repos: Optional[List[str]] = None,
    exclude_repos: Optional[List[str]] = None,
) -> List[Repository]:
    """Apply include/exclude filters to a list of repositories.

    Args:
        repos: List of Repository objects to filter.
        include_repos: Repo names to include, or ["all"].
        exclude_repos: Repo names to exclude (supports trailing *).

    Returns:
        Filtered list of Repository objects.
    """
    include_repos = include_repos or ["all"]
    exclude_repos = exclude_repos or []
    include_all = "all" in include_repos

    if not exclude_repos and include_all:
        return repos  # No filtering needed

    result = []
    for repo in repos:
        name = repo.name
        full_name = repo.full_name

        # Check exclude
        if _matches_any(name, full_name, exclude_repos):
            logger.debug("Excluding repo (filter): %s", full_name)
            continue

        # Check include
        if not include_all and not _matches_any(name, full_name, include_repos):
            logger.debug("Skipping repo (not in include list): %s", full_name)
            continue

        result.append(repo)

    return result


def _matches_any(name: str, full_name: str, patterns: List[str]) -> bool:
    """Check if a repo name matches any pattern in the list.

    Supports:
    - Exact match: "repo-name"
    - Trailing wildcard: "prefix-*"
    - Full name match: "owner/repo-name"

    Args:
        name: Repository short name.
        full_name: Repository full name (owner/repo).
        patterns: List of patterns to match against.

    Returns:
        True if any pattern matches.
    """
    for pattern in patterns:
        if pattern == "all":
            continue
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            if name.startswith(prefix) or full_name.startswith(prefix):
                return True
        else:
            if name == pattern or full_name == pattern:
                return True
    return False


# ---------------------------------------------------------------------------
# Summary data structure
# ---------------------------------------------------------------------------

class DiscoveryResult:
    """Container for all discovered content for one account.

    Attributes:
        account_name: Name of the account.
        personal_repos: List of personal repositories.
        gists: List of gists.
        orgs: Dict mapping org login -> list of repositories.
    """

    def __init__(self, account_name: str):
        self.account_name = account_name
        self.personal_repos: List[Repository] = []
        self.gists: List[Gist] = []
        self.orgs: dict = {}  # org_login -> List[Repository]

    def total_repos(self) -> int:
        """Total number of repositories across personal and all orgs."""
        org_total = sum(len(repos) for repos in self.orgs.values())
        return len(self.personal_repos) + org_total

    def total_gists(self) -> int:
        """Total number of gists."""
        return len(self.gists)

    def summary(self) -> str:
        """Human-readable summary of discovered content."""
        lines = [
            f"Account: {self.account_name}",
            f"  Personal repos: {len(self.personal_repos)}",
            f"  Gists: {len(self.gists)}",
            f"  Organizations: {len(self.orgs)}",
        ]
        for org_login, repos in sorted(self.orgs.items()):
            lines.append(f"    {org_login}: {len(repos)} repos")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main discovery entry points
# ---------------------------------------------------------------------------

def discover_all(
    gh: Github,
    account_config: dict,
    account_name: str,
    org_filter: Optional[str] = None,
) -> DiscoveryResult:
    """Enumerate all content for one account (without raw session).

    Args:
        gh: Authenticated PyGitHub client.
        account_config: Account configuration dict.
        account_name: Account name for logging.
        org_filter: If set, only discover this specific org.

    Returns:
        DiscoveryResult with all discovered content.
    """
    return discover_all_with_session(gh, None, account_config, account_name, org_filter)


def discover_all_with_session(
    gh: Github,
    gh_session,
    account_config: dict,
    account_name: str,
    org_filter: Optional[str] = None,
) -> DiscoveryResult:
    """Enumerate all content for one account.

    Args:
        gh: Authenticated PyGitHub client.
        gh_session: Authenticated requests.Session (for raw API org discovery).
        account_config: Account configuration dict.
        account_name: Account name for logging.
        org_filter: If set, only discover this specific org (from --org flag).

    Returns:
        DiscoveryResult with all discovered content.
    """
    result = DiscoveryResult(account_name)

    include_repos = account_config.get("include_repos", ["all"])
    exclude_repos = account_config.get("exclude_repos", [])
    include_orgs = account_config.get("include_orgs", ["all"])
    exclude_orgs = account_config.get("exclude_orgs", [])

    # If --org flag is set, override org filter
    if org_filter:
        include_orgs = [org_filter]
        logger.info("[%s] Limiting to org: %s", account_name, org_filter)

    # Personal repos
    raw_repos = discover_user_repos(gh, account_name)
    result.personal_repos = apply_repo_filters(raw_repos, include_repos, exclude_repos)

    # Gists
    result.gists = discover_gists(gh, account_name)

    # Organizations: use multi-method discovery for broad token compatibility
    org_logins = discover_org_logins(
        gh, gh_session, account_name, include_orgs, exclude_orgs,
    )

    for org_login in org_logins:
        try:
            org = gh.get_organization(org_login)
        except Exception as e:
            logger.error("[%s] Failed to get org %s: %s", account_name, org_login, e)
            continue
        raw_org_repos = discover_org_repos(org, account_name)
        filtered = apply_repo_filters(raw_org_repos, include_repos, exclude_repos)
        result.orgs[org.login] = filtered

    logger.info(
        "[%s] Discovery complete: %d repos, %d gists, %d orgs",
        account_name, result.total_repos(), result.total_gists(), len(result.orgs),
    )
    return result
