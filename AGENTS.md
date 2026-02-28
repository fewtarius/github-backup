# AGENTS.md

**Version:** 1.0  
**Date:** 2026-02-24  
**Purpose:** Technical reference for github-backup development (methodology in .clio/instructions.md)

---

## Project Overview

**github-backup** is a Python CLI tool that performs comprehensive, automated backups of all GitHub content accessible to one or more configured accounts.

- **Language:** Python 3.9+
- **Architecture:** CLI tool with modular package structure
- **Entry Point:** `github-backup` executable (wrapper) or `python -m github_backup`
- **Philosophy:** The Unbroken Method (see .clio/instructions.md)
- **PRD:** `.clio/PRD.md` - authoritative source for requirements and architecture decisions

---

## Quick Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Run backup (all accounts)
./github-backup run

# Dry-run: see what would be backed up
./github-backup list

# Create archive snapshot
./github-backup archive

# Check last run status
./github-backup status

# Debug/verbose run
./github-backup run --log-level debug
```

---

## Architecture

```
CLI Entry Point (github-backup or python -m github_backup)
    |
    v
cli.py (argparse, command dispatch)
    |
    v
config.py (load + validate JSON config)
    |
    v
auth.py (PAT setup, proxy configuration)
    |
    v
discovery.py (enumerate repos, gists, orgs via GitHub API)
    |
    v
mirror.py (git clone --mirror / git fetch --all)
    |
    v
metadata.py (issues, PRs, wikis, releases, assets via API)
    |
    v
resume.py (state tracking: what's been completed this run)
    |
    v
reporter.py (summary report to stdout + JSON log)
    |
    v
archive.py (tarball snapshot creation + pruning)
```

---

## Directory Structure

### Source Layout

```
github-backup/
├── github_backup/
│   ├── __init__.py
│   ├── __main__.py         # python -m entry point
│   ├── cli.py              # argparse, command dispatch
│   ├── config.py           # Config file discovery, loading, validation
│   ├── auth.py             # PAT authentication, proxy setup
│   ├── discovery.py        # Enumerate repos, gists, orgs via API
│   ├── mirror.py           # git mirror clone / fetch operations
│   ├── metadata.py         # Issues, PRs, wikis, releases, assets
│   ├── archive.py          # Tarball snapshot creation + pruning
│   ├── resume.py           # State tracking for resumable runs
│   ├── reporter.py         # Summary report generation
│   └── utils.py            # Logging, retry logic, helpers
├── tests/
│   ├── unit/               # Unit tests per module
│   └── integration/        # End-to-end tests
├── github-backup           # Executable wrapper script
├── requirements.txt
├── README.md
├── config.example.json
└── .clio/
    ├── PRD.md              # Product Requirements Document
    └── instructions.md     # Project methodology
```

### Backup Output Layout

```
<output_path>/
├── accounts/
│   └── <account-name>/
│       ├── repos/
│       │   └── <repo-name>.git/        # Bare mirror clone
│       ├── gists/
│       │   └── <gist-id>.git/          # Bare mirror clone
│       └── orgs/
│           └── <org-name>/
│               └── repos/
│                   └── <repo-name>.git/
├── metadata/
│   └── <account-name>/
│       ├── repos/
│       │   └── <repo-name>/
│       │       ├── repo.json
│       │       ├── issues.json
│       │       ├── pull_requests.json
│       │       ├── releases.json
│       │       └── assets/
│       ├── gists/
│       │   └── <gist-id>/
│       │       └── gist.json
│       └── orgs/
│           └── <org-name>/
│               ├── org.json
│               └── repos/
│                   └── <repo-name>/
│                       ├── repo.json
│                       ├── issues.json
│                       ├── pull_requests.json
│                       ├── releases.json
│                       └── assets/
├── archives/
│   └── github-backup-<YYYY-MM-DD>T<HH-MM-SS>.tar.gz
├── logs/
│   ├── last-run.json
│   └── github-backup-<YYYY-MM-DD>T<HH-MM-SS>.log
└── .run-state.json         # Resume state (deleted on successful completion)
```

---

## Configuration

### Config File Discovery Order

1. `--config PATH` CLI flag
2. `$GITHUB_BACKUP_CONFIG` environment variable
3. `~/.config/github-backup/config.json`
4. `./github-backup.json` (current working directory)

### Config Schema

```json
{
  "output_path": "/path/to/backup/directory",
  "proxy": {
    "http": "http://proxy.example.com:8080",
    "https": "http://proxy.example.com:8080",
    "no_proxy": "localhost,127.0.0.1"
  },
  "retry": {
    "max_attempts": 3,
    "backoff_seconds": 5
  },
  "archive": {
    "enabled": false,
    "keep_last": null,
    "keep_days": null
  },
  "accounts": [
    {
      "name": "my-personal-account",
      "token": "ghp_xxxxxxxxxxxxxxxxxxxx",
      "include_orgs": ["all"],
      "exclude_orgs": [],
      "include_repos": ["all"],
      "exclude_repos": []
    }
  ]
}
```

**Key config notes:**
- `include_orgs: ["all"]` = auto-discover all orgs; list specific names to limit
- `archive.enabled: false` is the default - archive is opt-in
- `archive.keep_last` and `archive.keep_days` are mutually usable (both applied if set)
- Proxy settings override environment variables (`HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`)

---

## CLI Interface

```
github-backup <command> [options]

Commands:
  run        Run backup for all configured accounts (default)
  archive    Create a dated tarball snapshot
  list       Dry-run: show content that would be backed up
  status     Show summary of last completed run

Global Options:
  --config PATH         Path to config file
  --output PATH         Override output directory from config
  --account NAME        Limit to a specific configured account
  --org NAME            Limit to a specific organization
  --log-level LEVEL     debug | info | warning | error (default: info)
  --no-color            Disable colored terminal output

Run Options:
  --dry-run             Alias for 'list' command
  --skip-metadata       Back up git content only
  --skip-assets         Skip downloading release asset binary files
  --force               Ignore resume state, reprocess all items
  --archive             Create archive after run completes

Archive Options:
  (archive pruning is config-driven, not CLI flags)
```

---

## Code Style

### Python Conventions

- **Python 3.9+** with type hints where practical
- **4 spaces** indentation (never tabs)
- **PEP 8** compliance
- **Docstrings** for all public functions and classes (Google style)
- **`pathlib.Path`** for all file path operations (not `os.path`)
- **`logging`** module for all output (not `print()`)
- **Dependency injection** for testability - pass config/clients in, don't import globals

### Module Template

```python
"""
github_backup.module_name - Brief description.

Detailed description of module purpose.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def function_name(param: str) -> Optional[str]:
    """Brief description.

    Args:
        param: Description of parameter.

    Returns:
        Description of return value, or None if not found.

    Raises:
        ValueError: If param is invalid.
    """
    logger.debug("Processing %s", param)
    # implementation
```

### Logging Conventions

```python
import logging
logger = logging.getLogger(__name__)

# Use module-level logger, never print()
logger.debug("Detailed trace: %s", value)
logger.info("Cloning %s/%s", account, repo)
logger.warning("Rate limit approaching: %d remaining", remaining)
logger.error("Failed to fetch %s after %d attempts", url, attempts)

# NEVER log tokens or credentials - sanitize before logging:
safe_url = url.replace(token, "***")
logger.debug("Fetching: %s", safe_url)
```

### Error Handling

```python
# Retry decorator pattern (from utils.py)
@retry(max_attempts=3, backoff=5)
def fetch_with_retry(url: str) -> dict:
    response = session.get(url)
    response.raise_for_status()
    return response.json()

# Don't let one failure stop the run - log and continue:
try:
    mirror_repo(repo)
    stats["success"] += 1
except Exception as e:
    logger.error("Failed to mirror %s: %s", repo.full_name, e)
    stats["failed"].append(repo.full_name)
    # continue to next repo
```

### File I/O

```python
from pathlib import Path
import json

# Always use pathlib
output_dir = Path(config["output_path"])
output_dir.mkdir(parents=True, exist_ok=True)

# JSON with pretty-printing for human readability
metadata_file = output_dir / "issues.json"
metadata_file.write_text(
    json.dumps(data, indent=2, ensure_ascii=False, default=str),
    encoding="utf-8"
)

# Atomic writes (prevents corruption on interrupt)
import tempfile, os
tmp = metadata_file.with_suffix(".tmp")
tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
tmp.rename(metadata_file)  # Atomic on Unix
```

---

## GitHub API Usage

### Authentication & Session Setup

```python
from github import Github  # PyGitHub
import requests

# PyGitHub client
gh = Github(token, per_page=100)

# requests Session (for raw API / asset downloads)
session = requests.Session()
session.headers["Authorization"] = f"token {token}"
session.headers["Accept"] = "application/vnd.github+json"

# Proxy setup
if proxy_config:
    session.proxies = {
        "http": proxy_config.get("http"),
        "https": proxy_config.get("https"),
    }
```

### Pagination

Always exhaust all pages - never truncate:

```python
# PyGitHub handles pagination automatically via PaginatedList
for repo in gh.get_user().get_repos():
    process(repo)

# For raw API calls, follow Link headers:
def get_all_pages(session, url):
    results = []
    while url:
        resp = session.get(url)
        resp.raise_for_status()
        results.extend(resp.json())
        url = resp.links.get("next", {}).get("url")
    return results
```

### Rate Limit Handling

```python
import time

def check_rate_limit(response):
    """Respect GitHub rate limits."""
    remaining = int(response.headers.get("X-RateLimit-Remaining", 1))
    if remaining == 0:
        reset_time = int(response.headers.get("X-RateLimit-Reset", 0))
        sleep_for = max(reset_time - time.time() + 1, 1)
        logger.warning("Rate limit hit. Sleeping %ds", sleep_for)
        time.sleep(sleep_for)
```

### Retry Logic

```python
import time
from functools import wraps

def retry(max_attempts=3, backoff_seconds=5):
    """Exponential backoff retry decorator."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    wait = backoff_seconds * (2 ** attempt)
                    logger.warning("Attempt %d failed: %s. Retrying in %ds",
                                   attempt + 1, e, wait)
                    time.sleep(wait)
        return wrapper
    return decorator
```

---

## Git Operations

### Mirror Clone (first run)

```python
import subprocess

def mirror_clone(clone_url: str, dest: Path, token: str) -> None:
    """Create a bare mirror clone."""
    # Embed token in URL (never persisted to disk after subprocess exits)
    auth_url = clone_url.replace("https://", f"https://x-token:{token}@")
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--mirror", auth_url, str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
```

### Mirror Update (subsequent runs)

```python
def mirror_fetch(dest: Path, token: str, remote_url: str) -> None:
    """Update an existing bare mirror clone."""
    # Update remote URL with current token
    subprocess.run(
        ["git", "-C", str(dest), "remote", "set-url", "origin",
         remote_url.replace("https://", f"https://x-token:{token}@")],
        check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(dest), "fetch", "--all", "--prune"],
        check=True, capture_output=True, text=True
    )
```

---

## Content Backed Up

| Content Type | Module | Method |
|-------------|--------|--------|
| Personal repos | `mirror.py` | `git clone --mirror` |
| Gists | `mirror.py` | `git clone --mirror` |
| Org repos | `mirror.py` | `git clone --mirror` |
| Wikis | `mirror.py` | `git clone --mirror` of `<repo>.wiki.git` |
| Issues + comments | `metadata.py` | REST API -> `issues.json` |
| PRs + reviews | `metadata.py` | REST API -> `pull_requests.json` |
| Releases + assets | `metadata.py` | REST API -> `releases.json` + binary download |
| Repo metadata | `metadata.py` | REST API -> `repo.json` |
| Org metadata | `metadata.py` | REST API -> `org.json` |
| Gist metadata | `metadata.py` | REST API -> `gist.json` |

---

## Resumability

```python
# .run-state.json tracks completed items:
{
    "run_started": "2026-02-24T14:30:00",
    "completed": [
        "account:myuser:repo:myrepo",
        "account:myuser:gist:abc123",
        "account:myuser:org:my-org:repo:some-repo"
    ]
}
```

- Load state at run start (if exists and `--force` not set)
- Check state before each item: skip if already in `completed`
- Write each item's key to state after successful completion (atomic write)
- Delete `.run-state.json` on successful run completion

---

## Archive Creation

```python
import tarfile
from datetime import datetime

def create_archive(output_path: Path, archive_dir: Path) -> Path:
    """Create a dated tarball snapshot."""
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    archive_name = f"github-backup-{timestamp}.tar.gz"
    archive_path = archive_dir / archive_name

    with tarfile.open(archive_path, "w:gz") as tar:
        # Add everything EXCEPT the archives/ subdirectory itself
        for item in output_path.iterdir():
            if item.name != "archives":
                tar.add(item, arcname=item.name)

    return archive_path
```

---

## Testing

### Before Committing

```bash
# 1. Syntax / import check
python -m py_compile github_backup/module.py

# 2. Check all modules
find github_backup -name "*.py" -exec python -m py_compile {} \;

# 3. Run unit tests
python -m pytest tests/unit/ -v

# 4. Run specific test
python -m pytest tests/unit/test_config.py -v

# 5. Run with coverage
python -m pytest tests/ --cov=github_backup --cov-report=term-missing

# 6. Dry run against real GitHub
./github-backup list --log-level debug
```

### Test Locations

- `tests/unit/` - Per-module tests with mocked API responses
- `tests/integration/` - End-to-end tests against a real test GitHub account

### Test Requirements

1. **Syntax must pass** - All `.py` files must compile without error
2. **Unit tests must exist** - New modules require corresponding test files
3. **Tests must pass** - `pytest` must exit 0
4. **Mock external calls** - Unit tests must not make real GitHub API calls
5. **Integration tests** - Use a dedicated test GitHub account/token

### New Module Checklist

1. Create `github_backup/new_module.py`
2. Create `tests/unit/test_new_module.py`
3. Run: `python -m pytest tests/unit/test_new_module.py -v`
4. Verify exit code 0

---

## Commit Format

```
type(scope): brief description

Problem: What was needed / what was broken
Solution: How it was implemented / fixed
Testing: How it was verified
```

**Types:** `feat`, `fix`, `refactor`, `docs`, `test`, `chore`

**Examples:**

```bash
git add -A
git commit -m "feat(mirror): implement bare mirror clone and fetch

Problem: No git backup mechanism existed
Solution: mirror_clone() uses git clone --mirror; mirror_fetch() uses git fetch --all --prune
Testing: Verified clone creates valid bare repo; fetch pulls new commits"
```

### Pre-Commit Checklist

- [ ] All `.py` files compile: `find github_backup -name "*.py" -exec python -m py_compile {} \;`
- [ ] `pytest tests/unit/` passes
- [ ] No tokens/credentials in code or test fixtures
- [ ] Docstrings updated for changed public functions
- [ ] No `TODO`/`FIXME` in committed code
- [ ] No `ai-assisted/` files staged: `git status`

---

## Dependencies

```
# requirements.txt
PyGitHub>=2.1.1     # GitHub API client
requests>=2.31.0    # HTTP client (also used by PyGitHub)
```

All other functionality uses Python standard library:
- `argparse` - CLI
- `json` - Config and metadata serialization
- `tarfile` - Archive creation
- `pathlib` - File path operations
- `logging` - All output
- `subprocess` - git operations
- `time` - Rate limit sleeping, backoff

---

## Security Rules

- **NEVER** log PATs, tokens, or credentials
- **NEVER** write tokens to disk (except in config file, which user owns)
- **ALWAYS** sanitize URLs containing tokens before logging
- Git clone URLs with embedded tokens are constructed in-memory and passed directly to subprocess - never persisted
- Config file permissions: document that users should `chmod 600` their config file
- `--log-level debug` must not expose token values

---

## Development Tools

```bash
# Check all syntax
find github_backup -name "*.py" -exec python -m py_compile {} \;

# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=github_backup

# Search codebase
grep -r "function_name" github_backup/

# Git operations
git status
git log --oneline -20
git diff

# Test dry-run (no GitHub API needed)
./github-backup list --config config.example.json

# Check what config is discovered
./github-backup status
```

---

## Common Patterns

### Processing All Items with Error Isolation

```python
# Never let one item failure stop the run
failed = []
succeeded = []

for repo in repos:
    try:
        process_repo(repo)
        succeeded.append(repo.full_name)
        resume_state.mark_complete(f"repo:{repo.full_name}")
    except Exception as e:
        logger.error("Failed: %s: %s", repo.full_name, e)
        failed.append((repo.full_name, str(e)))

# Report at end
return {"succeeded": succeeded, "failed": failed}
```

### Proxy-Aware Session Creation

```python
def create_session(token: str, proxy_config: dict = None) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    })
    if proxy_config:
        session.proxies = {k: v for k, v in proxy_config.items() if k != "no_proxy"}
        if "no_proxy" in proxy_config:
            session.trust_env = False  # Use our no_proxy, not env
    return session
```

---

## Documentation

| File | Purpose | Audience |
|------|---------|----------|
| `README.md` | Installation, quickstart, examples | Users |
| `config.example.json` | Annotated config template | Users |
| `AGENTS.md` | Technical reference | AI agents / developers |
| `.clio/instructions.md` | Project methodology | AI agents |
| `.clio/PRD.md` | Requirements & architecture | All |

---

## Anti-Patterns (What NOT To Do)

| Anti-Pattern | Why It's Wrong | What To Do |
|--------------|----------------|------------|
| `print()` for output | Bypasses log level control | Use `logger.info()` etc. |
| `os.path` for paths | Less readable, error-prone | Use `pathlib.Path` |
| Log raw clone URLs | Exposes tokens | Sanitize URLs before logging |
| Stop run on single failure | Loses all remaining backups | Catch exception, log, continue |
| Truncate paginated results | Incomplete backup | Always exhaust all pages |
| Hardcode output paths | Breaks on different systems | Use config + `pathlib.Path` |
| Skip rate limit handling | API ban risk | Always check rate limit headers |
| Skip resume check | Re-clones everything on retry | Always check `.run-state.json` |
| Import globals for config | Breaks testability | Inject config/clients as params |
| Commit `ai-assisted/` dir | Pollutes repository | Always `git reset HEAD ai-assisted/` |

---

*For project methodology and workflow, see .clio/instructions.md*  
*For requirements and architecture decisions, see .clio/PRD.md*  
*For universal agent behavior, see system prompt*
