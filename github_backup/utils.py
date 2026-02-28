"""
github_backup.utils - Shared utilities: retry logic, logging setup, helpers.
"""

import functools
import logging
import sys
import time
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

def retry(
    max_attempts: int = 3,
    backoff_seconds: float = 5.0,
    retriable_exceptions: tuple = (Exception,),
) -> Callable[[F], F]:
    """Exponential backoff retry decorator.

    On each failure, waits backoff_seconds * (2 ** attempt) before retrying.

    Args:
        max_attempts: Total number of attempts (including the first try).
        backoff_seconds: Base wait time in seconds.
        retriable_exceptions: Exception types to retry on.

    Returns:
        Decorator function.

    Example:
        @retry(max_attempts=3, backoff_seconds=5)
        def fetch_data(url):
            ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except retriable_exceptions as exc:
                    last_exception = exc
                    if attempt == max_attempts - 1:
                        logger.error(
                            "%s failed after %d attempts: %s",
                            func.__name__, max_attempts, exc,
                        )
                        raise
                    wait = backoff_seconds * (2 ** attempt)
                    logger.warning(
                        "%s attempt %d/%d failed: %s. Retrying in %.0fs...",
                        func.__name__, attempt + 1, max_attempts, exc, wait,
                    )
                    time.sleep(wait)
            raise last_exception  # pragma: no cover
        return wrapper  # type: ignore[return-value]
    return decorator


# ---------------------------------------------------------------------------
# GitHub rate limit helpers
# ---------------------------------------------------------------------------

def handle_rate_limit(response) -> None:
    """Sleep if a GitHub API response indicates rate limit exhaustion.

    Checks X-RateLimit-Remaining and X-RateLimit-Reset headers.

    Args:
        response: requests.Response object from a GitHub API call.
    """
    remaining = int(response.headers.get("X-RateLimit-Remaining", 1))
    if remaining == 0:
        reset_at = int(response.headers.get("X-RateLimit-Reset", 0))
        sleep_for = max(reset_at - time.time() + 2, 1)  # +2s buffer
        logger.warning(
            "GitHub API rate limit exhausted. Sleeping %.0fs until reset.", sleep_for
        )
        time.sleep(sleep_for)
    elif remaining < 50:
        logger.debug("GitHub API rate limit: %d requests remaining", remaining)


def check_rate_limit_from_github(gh_client) -> None:
    """Log current rate limit status from PyGitHub client.

    Args:
        gh_client: Authenticated PyGitHub Github instance.
    """
    try:
        rate_limit = gh_client.get_rate_limit()
        core = rate_limit.core
        logger.debug(
            "GitHub API rate limit: %d/%d remaining, resets at %s",
            core.remaining, core.limit, core.reset,
        )
        if core.remaining == 0:
            sleep_for = max((core.reset - time.time()) + 2, 1)
            logger.warning("Rate limit exhausted. Sleeping %.0fs.", sleep_for)
            time.sleep(sleep_for)
    except Exception as e:
        logger.debug("Could not check rate limit: %s", e)


# ---------------------------------------------------------------------------
# Pagination helper for raw REST API
# ---------------------------------------------------------------------------

def get_all_pages(session, url: str, params: Optional[dict] = None) -> list:
    """Fetch all pages of a paginated GitHub API endpoint.

    Follows Link: <url>; rel="next" headers until exhausted.

    Args:
        session: Authenticated requests.Session.
        url: Initial API URL.
        params: Optional query parameters for the first request.

    Returns:
        Combined list of all items across all pages.
    """
    results = []
    current_url = url
    current_params = params

    while current_url:
        response = session.get(current_url, params=current_params)
        response.raise_for_status()
        handle_rate_limit(response)

        data = response.json()
        if isinstance(data, list):
            results.extend(data)
        else:
            # Some endpoints return an object with an array field
            results.append(data)

        # Follow pagination
        current_url = response.links.get("next", {}).get("url")
        current_params = None  # Params are encoded in the next URL

    return results


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(level: str = "info", no_color: bool = False) -> None:
    """Configure root logger for the application.

    Args:
        level: Log level string (debug, info, warning, error).
        no_color: If True, disable ANSI color codes.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Format: timestamp, level, module, message
    if no_color or not sys.stderr.isatty():
        fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        datefmt = "%Y-%m-%dT%H:%M:%S"
        formatter = logging.Formatter(fmt, datefmt=datefmt)
    else:
        fmt = "%(asctime)s %(levelname_colored)s %(name)s: %(message)s"
        formatter = _ColorFormatter()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(numeric_level)
    root.handlers = []  # Clear any existing handlers
    root.addHandler(handler)

    # Quiet noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("github").setLevel(logging.WARNING)


class _ColorFormatter(logging.Formatter):
    """Log formatter with ANSI color codes for terminal output."""

    _COLORS = {
        logging.DEBUG: "\033[36m",     # Cyan
        logging.INFO: "\033[32m",      # Green
        logging.WARNING: "\033[33m",   # Yellow
        logging.ERROR: "\033[31m",     # Red
        logging.CRITICAL: "\033[35m",  # Magenta
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self._COLORS.get(record.levelno, "")
        record.levelname_colored = f"{color}[{record.levelname}]{self._RESET}"
        fmt = "%(asctime)s %(levelname_colored)s %(name)s: %(message)s"
        formatter = logging.Formatter(fmt, datefmt="%Y-%m-%dT%H:%M:%S")
        return formatter.format(record)


# ---------------------------------------------------------------------------
# Miscellaneous helpers
# ---------------------------------------------------------------------------

def safe_filename(name: str) -> str:
    """Sanitize a string for use as a filename.

    Replaces characters that are problematic on common filesystems.

    Args:
        name: Raw name string.

    Returns:
        Sanitized filename string.
    """
    # Replace chars that are unsafe on macOS/Linux/Windows
    replacements = {
        "/": "_",
        "\\": "_",
        ":": "_",
        "*": "_",
        "?": "_",
        '"': "_",
        "<": "_",
        ">": "_",
        "|": "_",
    }
    result = name
    for char, replacement in replacements.items():
        result = result.replace(char, replacement)
    return result.strip()


def format_duration(seconds: float) -> str:
    """Format a duration in seconds as a human-readable string.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted string like "1h 23m 45s" or "45s".
    """
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"
