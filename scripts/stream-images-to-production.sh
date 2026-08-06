#!/usr/bin/env bash
# Stream verified production images to the production host (silent pre-load, no publish).
#
# Runs ON the GitHub release runner. The staging release workflow triggers this
# after the public smoke checks pass. For each image it streams a `docker save |
# gzip` tar into a fixed relay directory on the production host, loads it from
# there (`docker load -i`, seekable file input), and verifies the loaded content
# ID equals the local image ID. It never touches compose, migrations, or running
# services. Publishing stays a manual Production promotion.
#
# The production host is reached over SSH with the whitelist-limited relay key
# (scripts/relay-allow.sh). Host, key, and pinned known_hosts are passed
# explicitly and never enter the repository. Local docker runs without sudo on
# the release runner; the remote relay commands keep `sudo -n`.
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/stream-images-to-production.sh <release-sha> [--throttle-mbps <mbps>]
       [--host <user@host>] [--ssh-key <path>] [--known-hosts <path>]

Streams the verified greatsellai-hr-api and greatsellai-hr-caddy images for the
given commit to the production host as `docker save | gzip | ssh sudo tee` into
the relay dir, then `docker load -i` from there.

--host, --ssh-key, and --known-hosts are required: the production host and the
whitelist-limited relay key, with its pinned known_hosts file. A non-zero
--throttle-mbps (default 0) caps the send rate via pv.

Fails closed: the local image must exist with revision == <release-sha>, and
after loading, the production image ID must equal the local image ID. Nothing
is published; promotion is a separate manual Production promotion.
EOF
}

die() {
  echo "Streaming to production error: $*" >&2
  exit 1
}

release_sha="${1:-}"
[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]] || { usage >&2; exit 1; }
shift 1

host=""
ssh_key=""
known_hosts=""
throttle_mbps=0
while (($#)); do
  case "$1" in
    --host) host="${2:?--host requires a value}"; shift 2 ;;
    --ssh-key) ssh_key="${2:?--ssh-key requires a value}"; shift 2 ;;
    --known-hosts) known_hosts="${2:?--known-hosts requires a value}"; shift 2 ;;
    --throttle-mbps) throttle_mbps="${2:?--throttle-mbps requires a value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ -n "$host" && "$host" == *@* ]] || die "--host must be user@hostname of the production host."
[[ -n "$ssh_key" ]] || die "Missing --ssh-key (path to the relay private key)."
[[ -n "$known_hosts" ]] || die "Missing --known-hosts (path to the pinned known_hosts)."
[[ -f "$ssh_key" ]] || die "Relay key not found at $ssh_key"
[[ -f "$known_hosts" ]] || die "known_hosts not found at $known_hosts"

[[ "$throttle_mbps" =~ ^[0-9]+$ ]] || die "Throttle rate must be a non-negative integer (0 disables throttling)."

throttle_cmd=()
if [[ "$throttle_mbps" -gt 0 ]]; then
  command -v pv >/dev/null 2>&1 || die "pv is required for throttling; install it (apt-get install -y pv)."
  throttle_cmd=(pv -L "${throttle_mbps}m")
fi

# Local docker needs no sudo on the release runner; fall back to sudo -n if it
# is only reachable through passwordless sudo (e.g. running this on a host).
docker_cmd=(docker)
docker version >/dev/null 2>&1 || docker_cmd=(sudo -n docker)

ssh_prod=(-o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$known_hosts" -i "$ssh_key" "$host")

ssh "${ssh_prod[@]}" true || die "Cannot reach production host $host."

# The relay whitelist (scripts/relay-allow.sh) restricts all writes/loads/removals
# to this exact directory; passwordless sudo is required on the production host.
relay_dir="/var/lib/greatsellai-relay"
ssh "${ssh_prod[@]}" "sudo -n mkdir -p $relay_dir" || die "Cannot prepare relay dir $relay_dir"

stream_image() {
  local image="$1"
  local tar="$relay_dir/${image%%:*}-${image##*:}.tar.gz"
  local local_id revision prod_id
  local_id="$("${docker_cmd[@]}" image inspect --format '{{.Id}}' "$image")" || \
    die "Local image $image is unavailable on the release runner."
  revision="$("${docker_cmd[@]}" image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$image")"
  [[ "$revision" == "$release_sha" ]] || die "Local image $image revision does not match $release_sha."

  echo "Streaming $image to $tar on production (throttle ${throttle_mbps}m)..."
  if [[ "${#throttle_cmd[@]}" -gt 0 ]]; then
    "${docker_cmd[@]}" save "$image" | gzip -1 | "${throttle_cmd[@]}" | ssh "${ssh_prod[@]}" "sudo -n tee $tar >/dev/null"
  else
    "${docker_cmd[@]}" save "$image" | gzip -1 | ssh "${ssh_prod[@]}" "sudo -n tee $tar >/dev/null"
  fi
  [[ "${PIPESTATUS[0]}" -eq 0 ]] || die "docker save of $image failed; nothing was loaded."

  echo "Loading $tar on production..."
  ssh "${ssh_prod[@]}" "sudo -n docker load -i $tar" || die "docker load -i of $tar failed."

  prod_id="$(ssh "${ssh_prod[@]}" "sudo -n docker image inspect --format '{{.Id}}' '$image'")" || \
    die "Preloaded production image $image is unavailable after load."
  [[ "$prod_id" == "$local_id" ]] || \
    die "Production image $image ID ($prod_id) differs from the runner image ID ($local_id)."
  echo "Preloaded $image -> $prod_id"

  ssh "${ssh_prod[@]}" "sudo -n rm -f $tar" || die "Could not remove $tar from production."
}

stream_image "greatsellai-hr-api:$release_sha"
stream_image "greatsellai-hr-caddy:$release_sha"

echo "Production host preloaded with $release_sha (images not published)."
