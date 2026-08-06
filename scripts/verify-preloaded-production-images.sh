#!/usr/bin/env bash
# Verify the production host holds the exact staging image content IDs for a
# silent-preloaded candidate, without transferring or building anything.
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/verify-preloaded-production-images.sh <release-sha> [options]

Options:
  --host <ssh-host>          Required production SSH target
  --api-image-id <sha256:id> Required staging-attested API image content ID
  --caddy-image-id <sha256:id>
                             Required staging-attested Caddy image content ID
  --ssh-key <path>           Optional SSH private-key path; never committed

This command does not transfer, build, tag, or deploy images. It fails closed
unless the production host already holds greatsellai-hr-api:<sha> and
greatsellai-hr-caddy:<sha> whose image IDs equal the completed staging record's
api_image_id/caddy_image_id, with revision == <release-sha> on linux/amd64.
EOF
}

die() {
  echo "Error: $*" >&2
  exit 1
}

shell_quote() {
  printf '%q' "$1"
}

release_commit="${1:-}"
[[ "$release_commit" =~ ^[0-9a-f]{40}$ ]] || { usage >&2; exit 1; }
shift

remote_host=""
api_image_id=""
caddy_image_id=""
ssh_key=""
while (($#)); do
  case "$1" in
    --host) remote_host="${2:?--host requires a value}"; shift 2 ;;
    --api-image-id) api_image_id="${2:?--api-image-id requires a value}"; shift 2 ;;
    --caddy-image-id) caddy_image_id="${2:?--caddy-image-id requires a value}"; shift 2 ;;
    --ssh-key) ssh_key="${2:?--ssh-key requires a value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ -n "$remote_host" ]] || die "Missing promotion target; pass --host."
[[ "$api_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "Invalid expected API image ID."
[[ "$caddy_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "Invalid expected Caddy image ID."
[[ "$api_image_id" != "$caddy_image_id" ]] || die "Expected API and Caddy image IDs must differ."
[[ -z "$ssh_key" || -r "$ssh_key" ]] || die "SSH key is not readable."

ssh_options=(-o BatchMode=yes -o StrictHostKeyChecking=yes)
if [[ -n "$ssh_key" ]]; then
  ssh_options+=(-i "$ssh_key" -o IdentitiesOnly=yes)
fi

remote_verify_script="$(cat <<'EOF'
set -Eeuo pipefail
release_commit="$1"
api_image_id="$2"
caddy_image_id="$3"

[[ "$release_commit" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Invalid promotion release commit." >&2
  exit 1
}
[[ "$api_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || {
  echo "Invalid expected API image ID." >&2
  exit 1
}
[[ "$caddy_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || {
  echo "Invalid expected Caddy image ID." >&2
  exit 1
}
[[ "$api_image_id" != "$caddy_image_id" ]] || {
  echo "Expected API and Caddy image IDs must differ." >&2
  exit 1
}

platform="$(sudo -n docker version --format '{{.Server.Os}}/{{.Server.Arch}}')" || {
  echo "Unable to inspect promotion Docker platform." >&2
  exit 1
}
[[ "$platform" == "linux/amd64" ]] || {
  echo "Promotion target platform must be linux/amd64; got $platform." >&2
  exit 1
}

require_preloaded_image() {
  local image="$1" expected_id="$2"
  local observed_id revision
  observed_id="$(sudo -n docker image inspect --format '{{.Id}}' "$image")" || {
    echo "Preloaded production image is unavailable: $image" >&2
    exit 1
  }
  [[ "$observed_id" == "$expected_id" ]] || {
    echo "Production image $image ID does not equal the completed staging record." >&2
    exit 1
  }
  revision="$(sudo -n docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$image")"
  [[ "$revision" == "$release_commit" ]] || {
    echo "Production image $image revision does not match $release_commit." >&2
    exit 1
  }
}

require_preloaded_image "greatsellai-hr-api:$release_commit" "$api_image_id"
require_preloaded_image "greatsellai-hr-caddy:$release_commit" "$caddy_image_id"
EOF
)"

ssh "${ssh_options[@]}" "$remote_host" \
  "bash -c $(shell_quote "$remote_verify_script") -- $(shell_quote "$release_commit") $(shell_quote "$api_image_id") $(shell_quote "$caddy_image_id")"

echo "Production host holds preloaded staging-attested images for $release_commit."
