#!/usr/bin/env bash
# release.sh - tag and push a new github-backup release
#
# Usage: ./release.sh v20260329.1

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "usage: $0 <tag>   (e.g. $0 v20260329.1)" >&2
    exit 1
fi

TAG="$1"

if [[ ! "$TAG" =~ ^v[0-9] ]]; then
    echo "error: tag must start with 'v' followed by a digit (got: $TAG)" >&2
    exit 1
fi

# Sanity checks
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "error: working tree is dirty - commit or stash changes first" >&2
    exit 1
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$BRANCH" != "main" ]]; then
    echo "error: must be on main branch (currently on: $BRANCH)" >&2
    exit 1
fi

echo "Tagging $TAG on main..."
git tag -a "$TAG" -m "github-backup $TAG"
git push origin main
git push origin "$TAG"
echo "Done - release pipeline triggered for $TAG"
