"""
github_backup.config - Configuration file discovery, loading, and validation.

Searches for config in the following order:
  1. --config PATH (CLI flag, passed as argument)
  2. $GITHUB_BACKUP_CONFIG environment variable
  3. ~/.config/github-backup/config.json
  4. ./github-backup.json (current working directory)
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default config structure with all optional fields
_DEFAULTS = {
    "retry": {
        "max_attempts": 3,
        "backoff_seconds": 5,
    },
    "archive": {
        "enabled": False,
        "keep_last": None,
        "keep_days": None,
    },
}

_SEARCH_PATHS = [
    Path.home() / ".config" / "github-backup" / "config.json",
    Path("github-backup.json"),
]


def discover_config_path(explicit_path: Optional[str] = None) -> Optional[Path]:
    """Find the config file location.

    Args:
        explicit_path: Path from --config CLI flag, if provided.

    Returns:
        Path to config file, or None if not found.
    """
    # 1. Explicit CLI flag
    if explicit_path:
        p = Path(explicit_path)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {explicit_path}")
        logger.debug("Using config from --config flag: %s", p)
        return p

    # 2. Environment variable
    env_path = os.environ.get("GITHUB_BACKUP_CONFIG")
    if env_path:
        p = Path(env_path)
        if not p.exists():
            raise FileNotFoundError(
                f"Config file from $GITHUB_BACKUP_CONFIG not found: {env_path}"
            )
        logger.debug("Using config from $GITHUB_BACKUP_CONFIG: %s", p)
        return p

    # 3 & 4. Search default locations
    for candidate in _SEARCH_PATHS:
        if candidate.exists():
            logger.debug("Found config at: %s", candidate)
            return candidate

    return None


def load_config(config_path: Optional[Path] = None) -> dict:
    """Load and validate the configuration file.

    Args:
        config_path: Path to config file. If None, auto-discovers.

    Returns:
        Validated configuration dictionary.

    Raises:
        FileNotFoundError: If no config file can be found.
        ValueError: If config is invalid.
    """
    if config_path is None:
        config_path = discover_config_path()

    if config_path is None:
        raise FileNotFoundError(
            "No configuration file found. Searched:\n"
            "  - $GITHUB_BACKUP_CONFIG\n"
            f"  - {_SEARCH_PATHS[0]}\n"
            f"  - {_SEARCH_PATHS[1]}\n\n"
            "Create a config file from the example:\n"
            "  cp config.example.json ~/.config/github-backup/config.json\n"
            "  chmod 600 ~/.config/github-backup/config.json\n"
            "  # Edit the file and add your GitHub tokens"
        )

    logger.info("Loading config from: %s", config_path)

    try:
        raw = config_path.read_text(encoding="utf-8")
        # Strip comment keys (keys starting with _) - allows annotated JSON
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Config file is not valid JSON: {config_path}\n{e}") from e

    config = _strip_comments(data)
    config = _apply_defaults(config)
    _validate_config(config)

    return config


def _strip_comments(data: dict) -> dict:
    """Remove keys starting with _ (used for inline documentation)."""
    if isinstance(data, dict):
        return {
            k: _strip_comments(v)
            for k, v in data.items()
            if not k.startswith("_")
        }
    elif isinstance(data, list):
        return [_strip_comments(item) for item in data]
    else:
        return data


def _apply_defaults(config: dict) -> dict:
    """Apply default values for optional config sections."""
    for section, defaults in _DEFAULTS.items():
        if section not in config:
            config[section] = defaults.copy()
        else:
            # Merge: keep user values, fill missing keys with defaults
            for key, default_val in defaults.items():
                config[section].setdefault(key, default_val)
    return config


def _validate_config(config: dict) -> None:
    """Validate required config fields.

    Args:
        config: Loaded configuration dictionary.

    Raises:
        ValueError: If required fields are missing or invalid.
    """
    errors = []

    # output_path is required
    if "output_path" not in config:
        errors.append("Missing required field: 'output_path'")
    elif not isinstance(config["output_path"], str) or not config["output_path"].strip():
        errors.append("'output_path' must be a non-empty string")

    # accounts is required
    if "accounts" not in config:
        errors.append("Missing required field: 'accounts'")
    elif not isinstance(config["accounts"], list) or len(config["accounts"]) == 0:
        errors.append("'accounts' must be a non-empty list")
    else:
        for i, account in enumerate(config["accounts"]):
            acct_errors = _validate_account(account, i)
            errors.extend(acct_errors)

    if errors:
        raise ValueError(
            "Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors)
        )


def _validate_account(account: dict, index: int) -> list:
    """Validate a single account configuration entry.

    Args:
        account: Account config dictionary.
        index: Position in accounts list (for error messages).

    Returns:
        List of error strings (empty if valid).
    """
    errors = []
    prefix = f"accounts[{index}]"

    if not isinstance(account, dict):
        return [f"{prefix}: must be an object"]

    # name
    if "name" not in account:
        errors.append(f"{prefix}: missing required field 'name'")
    elif not isinstance(account["name"], str) or not account["name"].strip():
        errors.append(f"{prefix}: 'name' must be a non-empty string")

    # token
    if "token" not in account:
        errors.append(f"{prefix}: missing required field 'token'")
    elif not isinstance(account["token"], str) or not account["token"].strip():
        errors.append(f"{prefix}: 'token' must be a non-empty string")
    elif account.get("token", "").startswith("ghp_xxxx"):
        errors.append(
            f"{prefix}: 'token' appears to be the example placeholder - "
            "please set a real GitHub Personal Access Token"
        )

    # include_orgs (optional, defaults to ["all"])
    include_orgs = account.get("include_orgs", ["all"])
    if not isinstance(include_orgs, list):
        errors.append(f"{prefix}: 'include_orgs' must be a list")

    # exclude_orgs (optional, defaults to [])
    if "exclude_orgs" in account and not isinstance(account["exclude_orgs"], list):
        errors.append(f"{prefix}: 'exclude_orgs' must be a list")

    return errors


def get_output_path(config: dict, override: Optional[str] = None) -> Path:
    """Resolve the output directory path.

    Args:
        config: Loaded configuration.
        override: Optional path override from --output CLI flag.

    Returns:
        Resolved output Path.
    """
    raw = override if override else config["output_path"]
    return Path(raw).expanduser().resolve()
