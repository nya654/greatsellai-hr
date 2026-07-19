#!/usr/bin/env bash
# Deploy only a GitHub production tag. Production data and environment files are
# intentionally never part of the transfer.
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

readonly default_host="ubuntu@58.87.96.20"
readonly default_project_dir="/home/ubuntu/resume-screening-v3"
readonly default_history_dir="/home/ubuntu/greatsellai-hr-deployments"

usage() {
  cat <<'EOF'
Usage: scripts/deploy-production.sh <prod-tag> [options]

Options:
  --host <ssh-host>         SSH target (default: ubuntu@58.87.96.20)
  --project-dir <path>      Live project directory on the server
  --history-dir <path>      Server-side release records and database backups
  --ssh-key <path>          Optional SSH private-key path; never committed
  --rollback                Deploy a prior tag as an application rollback
  --allow-schema-ahead      Required for rollback across migration changes;
                            keeps the current database schema and skips migrate

Only prod-YYYYMMDD-<commit-sha> tags that are reachable from origin/main are
accepted. The command transfers tracked source with git archive; it never uses
--delete and cannot transfer .env.production, Docker volumes, PDFs, or database data.
EOF
}

die() {
  echo "Error: $*" >&2
  exit 1
}

shell_quote() {
  printf '%q' "$1"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

tag="${1:-}"
[[ -n "$tag" && "$tag" != -* ]] || { usage >&2; exit 1; }
shift

remote_host="${RESUME_V3_DEPLOY_HOST:-$default_host}"
project_dir="${RESUME_V3_REMOTE_DIR:-$default_project_dir}"
history_dir="${RESUME_V3_DEPLOY_HISTORY_DIR:-$default_history_dir}"
ssh_key="${RESUME_V3_SSH_KEY:-}"
mode="deploy"
allow_schema_ahead=0

while (($#)); do
  case "$1" in
    --host) remote_host="${2:?--host requires a value}"; shift 2 ;;
    --project-dir) project_dir="${2:?--project-dir requires a value}"; shift 2 ;;
    --history-dir) history_dir="${2:?--history-dir requires a value}"; shift 2 ;;
    --ssh-key) ssh_key="${2:?--ssh-key requires a value}"; shift 2 ;;
    --rollback) mode="rollback"; shift ;;
    --allow-schema-ahead) allow_schema_ahead=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ "$tag" =~ ^prod-[0-9]{8}-[0-9a-f]{7,40}$ ]] || die "Invalid production tag: $tag"
[[ "$project_dir" == /home/ubuntu/* && "$project_dir" != /home/ubuntu/ ]] || \
  die "Refusing unsafe project directory: $project_dir"
[[ "$history_dir" == /home/ubuntu/* && "$history_dir" != /home/ubuntu/ ]] || \
  die "Refusing unsafe history directory: $history_dir"
[[ -z "$ssh_key" || -r "$ssh_key" ]] || die "SSH key is not readable."

if [[ -n "$(git status --porcelain)" ]]; then
  die "Refusing deployment from a dirty local worktree. Commit or stash changes first."
fi

git fetch origin main --tags --prune
release_commit="$(git rev-parse -q --verify "refs/tags/$tag^{commit}")" || die "Unknown local tag: $tag"
git ls-remote --exit-code --tags origin "refs/tags/$tag" >/dev/null 2>&1 || \
  die "Tag '$tag' has not been pushed to GitHub."
git merge-base --is-ancestor "$release_commit" origin/main || \
  die "Tag '$tag' is not reachable from origin/main."

ssh_options=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new)
if [[ -n "$ssh_key" ]]; then
  ssh_options+=(-i "$ssh_key" -o IdentitiesOnly=yes)
fi

ssh_run() {
  ssh "${ssh_options[@]}" "$remote_host" "$@"
}

remote_current="$(ssh_run "if [ -f $(shell_quote "$history_dir/current-release.env") ]; then sed -n -e 's/^tag=//p' -e 's/^commit=//p' $(shell_quote "$history_dir/current-release.env"); fi")"
previous_tag=""
previous_commit=""
while IFS= read -r line; do
  if [[ "$line" =~ ^prod-[0-9]{8}-[0-9a-f]{7,40}$ ]]; then
    previous_tag="$line"
  elif [[ "$line" =~ ^[0-9a-f]{40}$ ]]; then
    previous_commit="$line"
  fi
done <<< "$remote_current"

if [[ "$mode" == "rollback" ]]; then
  published_target="$(ssh_run "if [ -d $(shell_quote "$history_dir/releases") ] && grep -R -q -- $(shell_quote "^tag=$tag$") $(shell_quote "$history_dir/releases"); then printf yes; fi")"
  [[ "$published_target" == "yes" ]] || \
    die "Rollback target '$tag' has no successful production deployment record."
fi

migration_changed=0
if [[ -z "$previous_commit" ]]; then
  migration_changed=1
elif ! git cat-file -e "$previous_commit^{commit}" 2>/dev/null; then
  die "The recorded production commit is not available locally; fetch its release tag before deploying."
elif [[ -n "$(git diff --name-only "$previous_commit" "$release_commit" -- migrations/)" ]]; then
  migration_changed=1
fi

if [[ "$mode" == "rollback" && "$migration_changed" -eq 1 && "$allow_schema_ahead" -ne 1 ]]; then
  die "Rollback crosses migration changes. Review schema compatibility and retry with --allow-schema-ahead; this does not downgrade the database."
fi
if [[ "$mode" != "rollback" && "$allow_schema_ahead" -eq 1 ]]; then
  die "--allow-schema-ahead is only valid for an explicit rollback."
fi

backup_required=0
if [[ "$mode" == "deploy" && "$migration_changed" -eq 1 ]]; then
  backup_required=1
fi

ssh_run bash -s -- "$project_dir" "$history_dir" "$tag" "$release_commit" \
  "$previous_tag" "$previous_commit" "$mode" "$backup_required" <<'REMOTE_PRECHECK'
set -Eeuo pipefail
project_dir="$1"
history_dir="$2"
tag="$3"
release_commit="$4"
previous_tag="$5"
previous_commit="$6"
mode="$7"
backup_required="$8"

[ -f "$project_dir/compose.yml" ] || { echo "Live compose.yml is missing." >&2; exit 1; }
[ -f "$project_dir/.env.production" ] || { echo "Live .env.production is missing." >&2; exit 1; }
mkdir -p "$history_dir/releases" "$history_dir/backups"
chmod 700 "$history_dir" "$history_dir/releases" "$history_dir/backups"

if [ "$backup_required" = "1" ]; then
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  backup_path="$history_dir/backups/pre-${tag}-${timestamp}.sql.gz"
  umask 077
  sudo -n docker compose --project-directory "$project_dir" -f "$project_dir/compose.yml" \
    --env-file "$project_dir/.env.production" exec -T db \
    pg_dump -U resume_v3 -d resume_v3 | gzip > "$backup_path"
  test -s "$backup_path" || { echo "Database backup is empty." >&2; exit 1; }
fi

pending="$history_dir/pending-release.env"
umask 077
cat > "$pending" <<EOF
tag=$tag
commit=$release_commit
previous_tag=$previous_tag
previous_commit=$previous_commit
mode=$mode
backup_required=$backup_required
prepared_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
REMOTE_PRECHECK

# git archive contains tracked source only. It cannot include ignored production
# secrets or data, and extraction intentionally does not delete unknown files.
git archive --format=tar "$tag" | ssh "${ssh_options[@]}" "$remote_host" \
  "tar -x -C $(shell_quote "$project_dir")"

skip_migrate=0
if [[ "$mode" == "rollback" && "$migration_changed" -eq 1 ]]; then
  skip_migrate=1
fi

ssh_run bash -s -- "$project_dir" "$history_dir" "$tag" "$release_commit" \
  "$previous_tag" "$previous_commit" "$mode" "$skip_migrate" <<'REMOTE_DEPLOY'
set -Eeuo pipefail
project_dir="$1"
history_dir="$2"
tag="$3"
release_commit="$4"
previous_tag="$5"
previous_commit="$6"
mode="$7"
skip_migrate="$8"
compose=(sudo -n docker compose --project-directory "$project_dir" -f "$project_dir/compose.yml" --env-file "$project_dir/.env.production")

if [ "$skip_migrate" = "1" ]; then
  "${compose[@]}" up --build -d --no-deps api worker caddy
else
  "${compose[@]}" up --build -d api worker caddy
fi

"${compose[@]}" exec -T caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null

domain="$(sed -n 's/^RESUME_V3_DOMAIN=//p' "$project_dir/.env.production" | tail -n 1 | tr -d '\r' | sed -e 's/^"//' -e 's/"$//')"
[ -n "$domain" ] || { echo "RESUME_V3_DOMAIN is not set." >&2; exit 1; }

for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error --connect-timeout 5 --max-time 15 "https://$domain/health" >/dev/null; then
    break
  fi
  [ "$attempt" -eq 30 ] && { echo "HTTPS health check did not become ready." >&2; exit 1; }
  sleep 2
done

session_body="$(curl --fail --silent --show-error --connect-timeout 5 --max-time 15 "https://$domain/v1/auth/session")"
case "$session_body" in
  *'"authenticated":false'*'"login_required":true'*) ;;
  *) echo "Unexpected unauthenticated session response." >&2; exit 1 ;;
esac

protected_status="$(curl --silent --output /dev/null --write-out '%{http_code}' --connect-timeout 5 --max-time 15 \
  "https://$domain/v1/resumes/00000000-0000-0000-0000-000000000000/original-file")"
[ "$protected_status" = "401" ] || { echo "Protected PDF endpoint did not reject an unauthenticated request." >&2; exit 1; }

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
record="$history_dir/releases/${timestamp}-${tag}.env"
umask 077
cat > "$record" <<EOF
tag=$tag
commit=$release_commit
previous_tag=$previous_tag
previous_commit=$previous_commit
mode=$mode
database_schema_action=$( [ "$skip_migrate" = "1" ] && echo preserved || echo migrate_checked )
health_check=pass
session_protection=pass
protected_pdf_check=pass
deployed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
cp "$record" "$history_dir/current-release.env"
rm -f "$history_dir/pending-release.env"
printf 'Deployment recorded: %s\n' "$record"
REMOTE_DEPLOY

echo "Deployment succeeded: $tag ($release_commit)"
