#!/usr/bin/env bash
# Create an immutable staging candidate tag from the reviewed main branch.
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

usage() {
  cat <<'EOF'
Usage: scripts/create-staging-tag.sh [stg-YYYYMMDD-<N>]

Creates and pushes an annotated staging tag for the current, clean origin/main
commit. Without an argument the next daily counter tag (stg-YYYYMMDD-<N>) is
created. The command refuses to move or recreate an existing tag.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Refusing to tag from a dirty worktree." >&2
  exit 1
fi

git fetch origin main --tags --prune

current_branch="$(git branch --show-current)"
if [[ "$current_branch" != "main" ]]; then
  echo "Staging tags must be created from local main, not '$current_branch'." >&2
  exit 1
fi

head_commit="$(git rev-parse HEAD)"
origin_main_commit="$(git rev-parse origin/main)"
if [[ "$head_commit" != "$origin_main_commit" ]]; then
  echo "Local main must exactly match origin/main before tagging." >&2
  exit 1
fi

next_tag_number() {
  # Next daily counter tag (stg-YYYYMMDD-<N>). Count only same-day counter tags,
  # never historical <sha>-suffixed tags, then bump past any gap.
  local kind="$1"
  local prefix="${kind}-$(date -u +%Y%m%d)"
  local n
  n="$(git tag --list "${prefix}-*" | awk -v re="^${prefix}-[1-9][0-9]*\$" '$0 ~ re { c++ } END { print c+0 }')"
  n=$((n + 1))
  while git rev-parse -q --verify "refs/tags/${prefix}-${n}" >/dev/null 2>&1; do
    n=$((n + 1))
  done
  printf '%s-%s' "$prefix" "$n"
}

tag="${1:-$(next_tag_number stg)}"
if [[ ! "$tag" =~ ^stg-[0-9]{8}-([0-9a-f]{7,40}|[1-9][0-9]*)$ ]]; then
  echo "Invalid tag '$tag'. Expected stg-YYYYMMDD-<N> or stg-YYYYMMDD-<commit sha>." >&2
  exit 1
fi

if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
  echo "Tag '$tag' already exists locally and is immutable." >&2
  exit 1
fi
if git ls-remote --exit-code --tags origin "refs/tags/$tag" >/dev/null 2>&1; then
  echo "Tag '$tag' already exists on origin and is immutable." >&2
  exit 1
fi

git tag -a "$tag" -m "Staging candidate $tag" "$head_commit"
git push origin "refs/tags/$tag"

echo "Created and pushed $tag -> $head_commit"
