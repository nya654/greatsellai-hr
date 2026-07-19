#!/usr/bin/env bash
# Roll back application code to a previously published production tag.
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$repo_root/scripts/deploy-production.sh" "$@" --rollback
