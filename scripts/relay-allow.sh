#!/usr/bin/env bash
# Authorized-command whitelist for the staging-relay SSH key on the production
# host.
#
# Installed as /home/ubuntu/.relay-allow.sh on the production host and
# referenced by `command="/home/ubuntu/.relay-allow.sh"` in that host's
# authorized_keys (see .github/workflows/relay-bootstrap.yml). The staging
# host's silent-preload relay (scripts/stream-images-to-production.sh) may only:
#   - check reachability            (ssh production true)
#   - load an image from a tar      (docker load, streamed via save|gzip)
#   - read a greatsellai-hr content ID (docker image inspect --format '{{.Id}}')
# Every other command is denied, so this key can never open a shell, read
# files, or publish anything. Publishing stays a manual Production promotion,
# and promotion additionally re-verifies the preloaded image IDs against the
# completed staging record.
set -Eeuo pipefail

orig="${SSH_ORIGINAL_COMMAND:-}"

case "$orig" in
  "true")
    # Reachability probe used by the relay before streaming.
    exit 0
    ;;
  "sudo -n docker load" | "sudo docker load" | "docker load")
    exec sudo docker load
    ;;
  "sudo -n docker image inspect --format"* | "sudo docker image inspect --format"*)
    # Only the content-ID inspection of a greatsellai-hr image is permitted.
    image="${orig##* }"
    image="${image%\'}"
    image="${image#\'}"
    case "$image" in
      greatsellai-hr-api:* | greatsellai-hr-caddy:*)
        exec sudo docker image inspect --format '{{.Id}}' "$image"
        ;;
      *)
        echo "relay: not allowed image: $image" >&2
        exit 1
        ;;
    esac
    ;;
  *)
    echo "relay: command not allowed: ${orig:-<none>}" >&2
    exit 1
    ;;
esac
