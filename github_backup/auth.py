"""
github_backup.auth - GitHub authentication and HTTP session setup.

Creates authenticated PyGitHub clients and requests Sessions for each account,
with proxy support and token sanitization for logging.
"""

import logging
import os
from typing import Optional

import requests
from github import Github, Auth

logger = logging.getLogger(__name__)


def sanitize_url(url: str, token: str) -> str:
    """Remove token from a URL for safe logging.

    Args:
        url: URL that may contain an embedded token.
        token: The token to redact.

    Returns:
        URL with token replaced by ***.
    """
    if token and token in url:
        return url.replace(token, "***")
    return url


def _build_proxies(proxy_config: Optional[dict]) -> Optional[dict]:
    """Build a proxies dict for requests from config or environment.

    Config file proxy settings take precedence over environment variables.

    Args:
        proxy_config: Proxy section from config (may be None).

    Returns:
        Proxies dict suitable for requests.Session.proxies, or None.
    """
    if proxy_config:
        proxies = {}
        if proxy_config.get("http"):
            proxies["http"] = proxy_config["http"]
        if proxy_config.get("https"):
            proxies["https"] = proxy_config["https"]
        if proxies:
            logger.debug("Using proxy from config: %s", proxies.get("https") or proxies.get("http"))
            return proxies

    # Fall back to environment variables
    env_http = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    env_https = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if env_http or env_https:
        proxies = {}
        if env_http:
            proxies["http"] = env_http
        if env_https:
            proxies["https"] = env_https
        logger.debug("Using proxy from environment: %s", proxies.get("https") or proxies.get("http"))
        return proxies

    return None


def _build_no_proxy(proxy_config: Optional[dict]) -> Optional[str]:
    """Get no_proxy value from config or environment.

    Args:
        proxy_config: Proxy section from config.

    Returns:
        Comma-separated no_proxy string, or None.
    """
    if proxy_config and proxy_config.get("no_proxy"):
        return proxy_config["no_proxy"]
    return os.environ.get("NO_PROXY") or os.environ.get("no_proxy")


def create_session(token: str, proxy_config: Optional[dict] = None) -> requests.Session:
    """Create an authenticated requests.Session for GitHub API calls.

    Used for raw REST API calls, asset downloads, and endpoints not
    covered by PyGitHub.

    Args:
        token: GitHub Personal Access Token.
        proxy_config: Proxy configuration from config file.

    Returns:
        Configured requests.Session.
    """
    session = requests.Session()
    session.headers.update({
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })

    proxies = _build_proxies(proxy_config)
    if proxies:
        session.proxies.update(proxies)

    no_proxy = _build_no_proxy(proxy_config)
    if no_proxy and proxy_config:
        # When using config-defined proxy, disable env-based no_proxy
        # and use ours exclusively
        os.environ["NO_PROXY"] = no_proxy

    return session


def create_github_client(token: str, proxy_config: Optional[dict] = None) -> Github:
    """Create an authenticated PyGitHub client.

    Args:
        token: GitHub Personal Access Token.
        proxy_config: Proxy configuration from config file.

    Returns:
        Authenticated Github client instance.
    """
    proxies = _build_proxies(proxy_config)

    # PyGitHub accepts a requests session for proxy support
    if proxies:
        import github.Requester as Requester  # noqa: F401
        # Use a custom session injected via the Requester
        # (PyGitHub 2.x supports this via Auth + custom session)
        auth = Auth.Token(token)
        session = create_session(token, proxy_config)
        gh = Github(auth=auth, per_page=100)
        # Inject proxy into PyGitHub's internal session
        gh._Github__requester._Requester__session = session
    else:
        auth = Auth.Token(token)
        gh = Github(auth=auth, per_page=100)

    logger.debug("GitHub client created for account (token: ***%s)", token[-4:] if token else "????")
    return gh


def embed_token_in_url(clone_url: str, token: str) -> str:
    """Embed a PAT into an HTTPS clone URL for git authentication.

    The token is embedded in-memory only - never persisted to disk.
    The URL is used transiently for subprocess calls.

    Args:
        clone_url: HTTPS clone URL (e.g., https://github.com/user/repo.git)
        token: GitHub Personal Access Token.

    Returns:
        Authenticated URL (e.g., https://x-token:ghp_xxx@github.com/user/repo.git)
    """
    if clone_url.startswith("https://"):
        return clone_url.replace("https://", f"https://x-token:{token}@", 1)
    return clone_url


class AccountAuth:
    """Authentication context for a single GitHub account.

    Bundles together the token, PyGitHub client, and requests session
    for a configured account.

    Attributes:
        name: Account name from config.
        token: Personal Access Token (never logged).
        gh: Authenticated PyGitHub client.
        session: Authenticated requests.Session.
    """

    def __init__(self, account_config: dict, proxy_config: Optional[dict] = None):
        """Initialize auth for one account.

        Args:
            account_config: Single account entry from config['accounts'].
            proxy_config: Proxy section from top-level config.
        """
        self.name = account_config["name"]
        self.token = account_config["token"]
        self._proxy_config = proxy_config

        logger.info("Initializing auth for account: %s", self.name)
        self.gh = create_github_client(self.token, proxy_config)
        self.session = create_session(self.token, proxy_config)

    def authenticated_clone_url(self, clone_url: str) -> str:
        """Return a clone URL with embedded token for git subprocess calls.

        Args:
            clone_url: Plain HTTPS clone URL.

        Returns:
            HTTPS URL with token embedded (in-memory only).
        """
        return embed_token_in_url(clone_url, self.token)

    def safe_url(self, url: str) -> str:
        """Sanitize a URL for safe logging (redacts token).

        Args:
            url: URL that may contain the token.

        Returns:
            URL with token replaced by ***.
        """
        return sanitize_url(url, self.token)
