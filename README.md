# github-backup

A comprehensive GitHub backup tool that mirrors **all** content from your GitHub accounts - personal repositories, gists, organizations, wikis, issues, pull requests, releases, and binary assets - to local storage.

## Features

- **100% content coverage**: git repos (bare mirror), gists, wikis, issues + comments, PRs + reviews, releases + binary assets, org/repo/gist metadata
- **Multi-account support**: backup multiple GitHub accounts with separate tokens
- **Organization auto-discovery**: finds all orgs you belong to automatically
- **Incremental updates**: first run clones, subsequent runs fetch only changes
- **Resumable**: interrupted runs resume where they left off
- **Archive snapshots**: create dated tarball archives of your backup directory
- **Proxy support**: works behind HTTP/HTTPS proxies
- **Cron-friendly**: structured logging, exit codes, summary reports

## Requirements

- Python 3.9+
- `git` (must be on PATH)
- GitHub Personal Access Token with scopes: `repo`, `read:org`, `gist`, `read:user`

## Installation

```bash
git clone https://github.com/fewtarius/github-backup.git
cd github-backup
pip3 install -r requirements.txt
chmod +x github-backup
```

## Configuration

Copy the example config and edit it:

```bash
mkdir -p ~/.config/github-backup
cp config.example.json ~/.config/github-backup/config.json
chmod 600 ~/.config/github-backup/config.json
```

Edit `~/.config/github-backup/config.json`:

```json
{
  "output_path": "/path/to/your/backup/directory",
  "accounts": [
    {
      "name": "my-personal-account",
      "token": "ghp_your_real_token_here",
      "include_orgs": ["all"],
      "exclude_orgs": [],
      "include_repos": ["all"],
      "exclude_repos": []
    }
  ]
}
```

### Config File Discovery Order

The tool searches for config in this order:

1. `--config PATH` CLI flag
2. `$GITHUB_BACKUP_CONFIG` environment variable
3. `~/.config/github-backup/config.json`
4. `./github-backup.json` (current directory)

### Full Config Reference

```json
{
  "output_path": "/backups/github",
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
      "name": "personal",
      "token": "ghp_...",
      "include_orgs": ["all"],
      "exclude_orgs": ["some-org-to-skip"],
      "include_repos": ["all"],
      "exclude_repos": ["archived-*"]
    },
    {
      "name": "work",
      "token": "ghp_...",
      "include_orgs": ["my-company"],
      "exclude_orgs": [],
      "include_repos": ["all"],
      "exclude_repos": []
    }
  ]
}
```

**`include_orgs`**: `["all"]` auto-discovers all orgs. List specific org names to limit.  
**`exclude_repos`**: Supports trailing wildcard: `"archived-*"` excludes any repo starting with `archived-`.  
**`archive.keep_last`**: Keep only N most recent archives (null = unlimited).  
**`archive.keep_days`**: Delete archives older than N days (null = unlimited).

## Usage

### Run a backup

```bash
# Backup all configured accounts
./github-backup run

# Backup a specific account
./github-backup run --account my-personal-account

# Backup a specific organization
./github-backup run --org my-company

# Skip metadata (git content only, faster)
./github-backup run --skip-metadata

# Skip binary asset downloads
./github-backup run --skip-assets

# Force full re-run (ignore resume state)
./github-backup run --force

# Run backup + create archive in one step
./github-backup run --archive
```

### Preview what would be backed up (dry run)

```bash
./github-backup list
./github-backup run --dry-run  # same thing
```

### Create a snapshot archive

```bash
./github-backup archive
```

Creates: `<output_path>/archives/github-backup-2026-02-24T14-30-00.tar.gz`

### Check last run status

```bash
./github-backup status
```

### Verbose / debug output

```bash
./github-backup run --log-level debug
./github-backup run --log-level warning --no-color  # for cron
```

## Cron Setup

```bash
# Edit crontab
crontab -e

# Run daily at 2am, log to file
0 2 * * * /path/to/github-backup/github-backup run --log-level warning --no-color >> /var/log/github-backup.log 2>&1

# Run weekly with archive
0 3 * * 0 /path/to/github-backup/github-backup run --archive --log-level warning --no-color >> /var/log/github-backup.log 2>&1
```

## Output Directory Layout

```
<output_path>/
├── accounts/
│   └── <account-name>/
│       ├── repos/
│       │   ├── my-repo.git/          # Bare mirror clone
│       │   └── my-repo.wiki.git/     # Wiki mirror (if exists)
│       ├── gists/
│       │   └── abc123def456.git/
│       └── orgs/
│           └── my-org/
│               └── repos/
│                   └── org-repo.git/
├── metadata/
│   └── <account-name>/
│       ├── repos/
│       │   └── my-repo/
│       │       ├── repo.json
│       │       ├── issues.json        # All issues + comments
│       │       ├── pull_requests.json # All PRs + reviews
│       │       ├── releases.json
│       │       └── assets/
│       │           └── v1.0.0/
│       │               └── app-v1.0.0-linux-amd64.tar.gz
│       ├── gists/
│       │   └── abc123def456/
│       │       └── gist.json
│       └── orgs/
│           └── my-org/
│               ├── org.json
│               └── repos/
│                   └── org-repo/
│                       ├── repo.json
│                       ├── issues.json
│                       └── ...
├── archives/
│   └── github-backup-2026-02-24T02-00-00.tar.gz
└── logs/
    └── last-run.json
```

## Restoring from Backup

### Restore a git repository

```bash
# Clone from the bare mirror
git clone /backups/github/accounts/myuser/repos/my-repo.git my-repo

# Or push to a new remote
cd /backups/github/accounts/myuser/repos/my-repo.git
git push --mirror https://github.com/myuser/restored-repo.git
```

### Access metadata

All metadata is stored as human-readable JSON:

```bash
# Browse issues
cat /backups/github/metadata/myuser/repos/my-repo/issues.json | python3 -m json.tool | less

# Count PRs
python3 -c "import json; data=json.load(open('/backups/.../pull_requests.json')); print(len(data), 'PRs')"
```

## Security

- **Protect your config file**: `chmod 600 ~/.config/github-backup/config.json`
- Tokens are never logged or written to disk (except in your config file)
- Git clone URLs with embedded tokens are constructed in-memory for subprocess calls only

## Required Token Scopes

When creating a GitHub Personal Access Token, enable:

| Scope | Purpose |
|-------|---------|
| `repo` | Read private repositories |
| `read:org` | Discover and read organization repos |
| `gist` | Read private gists |
| `read:user` | Read user profile |

Create a token at: <https://github.com/settings/tokens>

## Troubleshooting

**"No configuration file found"**  
→ Copy `config.example.json` to `~/.config/github-backup/config.json` and edit it.

**"token appears to be the example placeholder"**  
→ Replace the `ghp_xxxx...` token in your config with a real GitHub PAT.

**Rate limit errors**  
→ The tool automatically respects GitHub's rate limits and sleeps until reset. For large accounts, backups may take several hours on first run.

**Incomplete backup after interruption**  
→ Just re-run `./github-backup run`. The resume state file (`.run-state.json`) tracks what was completed. Use `--force` to ignore it and start fresh.

**Wiki clone fails**  
→ Not all repos have wikis enabled. Wiki failures are non-fatal and logged at DEBUG level.


## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.
