# Product Requirements Document: github-backup

**Version:** 1.0  
**Date:** 2026-02-24  
**Status:** Complete

---

## 1. Project Overview

### 1.1 Summary

`github-backup` is a Python-based command-line tool that performs comprehensive, automated backups of all GitHub content accessible to one or more configured accounts. It mirrors git repositories (personal and organizational), gists, and all associated metadata (issues, pull requests, wikis, releases, and assets) to a local directory structure. It supports dated archive snapshots and is designed to be run manually or via cron.

### 1.2 Problem Statement

GitHub hosts critical source code, documentation, and collaborative history. There is no native, first-party mechanism to perform a complete local backup of all content associated with a GitHub account - including organizational repositories, gists, issue threads, pull request history, and release assets. Relying solely on GitHub as the single source of truth exposes users to risk from accidental deletion, account suspension, or service outages.

### 1.3 Goals

- Provide 100% coverage of all accessible GitHub content for one or more accounts
- Make initial setup trivial and subsequent runs idempotent (update, not re-clone)
- Produce a human-navigable, restorable directory structure
- Support point-in-time archive snapshots for long-term retention
- Be safe to schedule via cron with reliable logging and error recovery

### 1.4 Non-Goals

- Real-time sync or webhook-triggered backup (cron is sufficient)
- GitHub Enterprise Server support (out of scope for v1)
- GUI or web interface
- Cloud storage backends (local filesystem only in v1)

---

## 2. Users & Use Cases

### 2.1 Target Users

- Individual developers backing up personal GitHub accounts
- Power users managing multiple GitHub accounts or identities
- Teams wanting a local mirror of organizational repositories

### 2.2 Primary Use Cases

| Use Case | Description |
|----------|-------------|
| Initial backup | First run clones all content for a configured account |
| Incremental update | Subsequent runs fetch latest changes, adding new repos/gists, updating existing ones |
| Point-in-time snapshot | User creates a dated tarball archive of the entire backup directory |
| Selective backup | User limits a run to a specific account or organization |
| Dry run | User previews what would be backed up without making changes |
| Status check | User reviews the last run's summary report |

---

## 3. Technical Architecture

### 3.1 Technology Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python 3.9+ | Strong GitHub API support, readable, maintainable |
| GitHub API | `PyGitHub` + raw REST/GraphQL | Broad coverage; fallback to raw API for endpoints not in SDK |
| HTTP client | `requests` (via PyGitHub) | Industry standard, proxy support built-in |
| Git operations | `git` CLI (subprocess) | Native mirror clone/fetch behavior |
| JSON config | stdlib `json` | No extra deps; matches user preference |
| Archiving | stdlib `tarfile` | No extra deps for archive creation |
| CLI | `argparse` (stdlib) | Simple, no extra deps |

### 3.2 Directory Structure

#### Installation Layout
```
github-backup/
├── github_backup/
│   ├── __init__.py
│   ├── __main__.py         # Entry point: python -m github_backup
│   ├── cli.py              # Argument parsing, command dispatch
│   ├── config.py           # Config file discovery, loading, validation
│   ├── auth.py             # PAT authentication, proxy setup
│   ├── discovery.py        # Enumerate repos, gists, orgs via API
│   ├── mirror.py           # git mirror clone / fetch operations
│   ├── metadata.py         # Issues, PRs, wikis, releases, assets
│   ├── archive.py          # Tarball snapshot creation
│   ├── resume.py           # State tracking for resumable runs
│   ├── reporter.py         # Summary report generation
│   └── utils.py            # Logging, retry logic, helpers
├── github-backup           # Executable wrapper script
├── requirements.txt
├── README.md
└── config.example.json
```

#### Backup Output Layout
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
│       │       ├── repo.json           # Repo metadata
│       │       ├── issues.json
│       │       ├── pull_requests.json
│       │       ├── releases.json
│       │       └── assets/             # Release asset files
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
│   └── github-backup-2026-02-24T14-30-00.tar.gz
└── logs/
    ├── last-run.json       # Machine-readable summary of last run
    └── github-backup-2026-02-24T14-30-00.log
```

### 3.3 Configuration

#### Config File Discovery Order
1. Path specified via `--config` CLI flag
2. `$GITHUB_BACKUP_CONFIG` environment variable
3. `~/.config/github-backup/config.json`
4. `./github-backup.json` (current working directory)

#### Config Schema
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
    },
    {
      "name": "work-account",
      "token": "ghp_yyyyyyyyyyyyyyyyyyyy",
      "include_orgs": ["my-company"],
      "exclude_orgs": [],
      "include_repos": ["all"],
      "exclude_repos": ["archived-*"]
    }
  ]
}
```

**Config field notes:**
- `include_orgs`: `["all"]` discovers all orgs automatically; list specific org names to limit
- `archive.keep_last`: integer, keep last N archives (null = unlimited)
- `archive.keep_days`: integer, delete archives older than N days (null = unlimited)
- `archive.enabled`: default `false`; pruning only applies when enabled

---

## 4. Feature Specifications

### 4.1 CLI Interface

```
Usage: github-backup <command> [options]

Commands:
  run        Run backup for all configured accounts (default)
  archive    Create a dated tarball snapshot of the backup directory
  list       Dry-run: show all content that would be backed up
  status     Display summary of the last completed run

Global Options:
  --config PATH         Path to config file
  --output PATH         Override output directory
  --account NAME        Limit to a specific configured account
  --org NAME            Limit to a specific organization
  --log-level LEVEL     Logging verbosity: debug, info, warning, error (default: info)
  --no-color            Disable colored terminal output
  -h, --help            Show help

Run Options:
  --dry-run             Preview actions without making changes (alias for 'list')
  --skip-metadata       Back up git content only, skip issues/PRs/etc.
  --skip-assets         Skip downloading release asset binary files
  --force               Ignore resume state, re-process all items

Archive Options:
  --archive             Also create an archive after running (run + archive)
```

### 4.2 Content Backup Scope

| Content Type | Backed Up | Method |
|-------------|-----------|--------|
| Personal repositories | Yes | `git clone --mirror` / `git fetch --all` |
| Personal gists | Yes | `git clone --mirror` / `git fetch --all` |
| Organization repositories | Yes | `git clone --mirror` / `git fetch --all` |
| Repository wikis | Yes | `git clone --mirror` of `<repo>.wiki.git` |
| Issues (all, open+closed) | Yes | GitHub REST API -> JSON |
| Issue comments | Yes | GitHub REST API -> JSON (embedded in issues.json) |
| Pull requests (all) | Yes | GitHub REST API -> JSON |
| PR reviews & comments | Yes | GitHub REST API -> JSON (embedded) |
| Releases | Yes | GitHub REST API -> JSON |
| Release assets | Yes | Downloaded as binary files |
| Repository metadata | Yes | GitHub REST API -> JSON (description, topics, settings) |
| Gist metadata | Yes | GitHub REST API -> JSON |
| Organization metadata | Yes | GitHub REST API -> JSON |
| GitHub Actions workflows | Yes | Stored in repo mirror (`.github/workflows/`) |
| Actions run history | No | Out of scope for v1 |
| GitHub Packages | No | Out of scope for v1 |
| GitHub Projects (v2) | No | Out of scope for v1 |

### 4.3 Git Mirror Operations

- **First run:** `git clone --mirror <url> <dest>.git`
- **Subsequent runs:** `git -C <dest>.git fetch --all --prune`
- Authentication injected via credential helper or HTTPS URL with token embedded
- Mirror clones preserve all refs (branches, tags, pull request refs)

### 4.4 Metadata Collection

- All paginated API responses are fully consumed (no truncation)
- Each resource saved as pretty-printed JSON for human readability
- Metadata re-fetched on every run (always current, not incremental)
- Timestamps preserved from API responses

### 4.5 Retry Logic

- Configurable `max_attempts` (default: 3) and `backoff_seconds` (default: 5)
- Exponential backoff: wait = `backoff_seconds * (2 ^ attempt)`
- Retry on: network errors, HTTP 429 (rate limit), HTTP 5xx (server errors)
- GitHub rate limit headers (`X-RateLimit-Reset`) respected: sleep until reset if limit hit
- Failures after all retries: logged, item skipped, run continues

### 4.6 Resumability

- Run state tracked in `<output_path>/.run-state.json`
- State records: list of completed repo/gist IDs for the current run session
- On interrupt and restart: already-completed items skipped (unless `--force`)
- State file cleared at successful run completion

### 4.7 Archive / Snapshot

- Command: `github-backup archive`
- Creates: `<output_path>/archives/github-backup-<YYYY-MM-DD>T<HH-MM-SS>.tar.gz`
- Timestamps to the minute to support multiple snapshots per day
- Archives entire `<output_path>` **excluding** the `archives/` subdirectory (no nested archives)
- Pruning (when configured): runs after archive creation, removes oldest archives first

### 4.8 Summary Report

Displayed to stdout at end of each run and saved to `<output_path>/logs/last-run.json`:

```
=== github-backup Run Summary ===
Started:    2026-02-24 14:30:00
Finished:   2026-02-24 15:45:12
Duration:   1h 15m 12s

Account: my-personal-account
  Repositories:   42 updated, 2 new, 0 failed
  Gists:          7 updated, 0 new, 0 failed
  Organizations:  3 discovered
    org-one:      18 repos updated, 0 failed
    org-two:      5 repos updated, 1 failed
    org-three:    12 repos updated, 0 new, 0 failed
  Metadata:       completed (issues, PRs, releases, assets)

Failures (1):
  [ERROR] org-two/secret-repo: git fetch failed after 3 attempts
          Error: Repository not found (403)

Total: 84 repositories, 7 gists, 0 archives created
```

### 4.9 Proxy Support

- Proxy settings in config file under `proxy` key
- Also reads standard environment variables: `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`
- Config file proxy settings take precedence over environment variables
- Applied to all HTTP(S) requests (API calls and asset downloads)
- Git operations: `GIT_CONFIG` env vars set (`http.proxy`) for subprocess calls

### 4.10 Authentication

- Personal Access Token (PAT) per account in config file
- Required token scopes: `repo`, `read:org`, `gist`, `read:user`
- Token passed via `Authorization: token <PAT>` header
- For git operations: token embedded in HTTPS clone URL or via `GIT_ASKPASS` helper
- Token never written to disk outside of config file

---

## 5. Development Phases

### Phase 1 - Core MVP (Week 1-2)

- [x] Project scaffolding (directory structure, `requirements.txt`, entry point)
- [x] Config file loading with auto-discovery
- [x] GitHub authentication (single account, PAT)
- [x] Repository discovery (personal repos + orgs)
- [x] Bare mirror clone and fetch
- [x] Basic CLI (`run`, `--account`, `--org`)
- [x] Console logging

### Phase 2 - Full Content (Week 2-3)

- [x] Gist discovery and mirror
- [x] Organization auto-discovery
- [x] Metadata collection (issues, PRs, releases)
- [x] Release asset downloading
- [x] Wiki mirror support
- [x] Resume/state tracking

### Phase 3 - Reliability & Polish (Week 3-4)

- [x] Retry logic with exponential backoff + rate limit handling
- [x] Proxy support
- [x] Summary report (stdout + JSON log)
- [x] Multi-account support
- [x] `list` / dry-run command
- [x] `status` command

### Phase 4 - Archive & Distribution (Week 4)

- [x] `archive` command with dated tarballs
- [x] Archive pruning (keep_last, keep_days)
- [x] `--archive` flag on `run` command
- [x] README and config.example.json
- [x] `github-backup` wrapper executable script

---

## 6. Testing Strategy

### 6.1 Unit Tests

- Config loading and validation (valid/invalid/missing fields)
- Discovery logic with mocked API responses
- Retry logic (mock failures, verify backoff behavior)
- Archive creation and pruning logic
- Resume state read/write/clear

### 6.2 Integration Tests

- End-to-end run against a real test GitHub account with known repos/gists
- Verify mirror clone is valid (`git log`, `git ls-remote`)
- Verify metadata JSON is valid and complete
- Verify incremental run detects and fetches new commits
- Verify archive is created and extractable

### 6.3 Manual Validation Checklist

- [ ] First run on fresh output directory completes without errors
- [ ] Second run on same directory updates without re-cloning
- [ ] Run interrupted mid-way; restart resumes correctly
- [ ] `--org` flag limits scope correctly
- [ ] `--account` flag limits scope correctly
- [ ] `archive` command produces valid, extractable tarball
- [ ] Proxy config routes all traffic through proxy
- [ ] Failed repo logged but run continues

---

## 7. Security Considerations

- PATs stored only in config file; user responsible for file permissions (`chmod 600`)
- Tokens never logged, never appear in error messages
- No credentials transmitted to third parties
- Git clone URLs with embedded tokens not persisted to disk (used in-memory only)
- `--log-level debug` must not expose token values

---

## 8. Open Questions / Future Considerations

| Topic | Notes |
|-------|-------|
| GitHub Enterprise Server | Could be added in v2 with configurable `base_url` per account |
| Cloud storage backends | S3, GCS, Azure Blob as optional destinations (v2) |
| GitHub Actions run history | Large data volume; requires separate consideration |
| GitHub Projects v2 | GraphQL-heavy; complex to serialize; v2 candidate |
| Notifications | Email/webhook on failure after cron run |
| Compression level | Currently default gzip; could expose `--compression` flag |
| Parallel downloads | Asset downloads could be parallelized for speed |

---

*Document prepared by CLIO Application Architect assistant, 2026-02-24*
