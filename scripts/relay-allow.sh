#!/usr/bin/env bash
# Authorized-command whitelist for the staging-relay SSH key on the production
# host.
#
# Installed as /home/ubuntu/.relay-allow.sh on the production host and
# referenced by `command="/home/ubuntu/.relay-allow.sh"` in that host's
# authorized_keys (see .github/workflows/relay-bootstrap.yml). The staging
# host's silent-preload relay (scripts/stream-images-to-production.sh) may only:
#   - check reachability                (ssh production true)
#   - prepare the relay dir             (sudo -n mkdir -p /var/lib/greatsellai-relay)
#   - stream a docker-save tar into it  (sudo -n tee /var/lib/greatsellai-relay/<file> >/dev/null)
#   - load an image from that tar       (docker load -i /var/lib/greatsellai-relay/<file>)
#   - delete a consumed tar             (rm -f /var/lib/greatsellai-relay/<file>)
#   - read a greatsellai-hr content ID  (docker image inspect --format '{{.Id}}')
# Every other command is denied, so this key can never open a shell, read
# arbitrary files, or publish anything. The streamed tar is inert data (a
# docker-save archive): even a malicious tar cannot execute on its own, and
# loading it still requires the whitelisted `docker load -i` plus the manual
# Production promotion ID re-check.
set -Eeuo pipefail

orig="${SSH_ORIGINAL_COMMAND:-}"
RELAY_DIR=/var/lib/greatsellai-relay

case "$orig" in
  "true")
    # Reachability probe used by the relay before streaming.
    exit 0
    ;;
  "sudo -n mkdir -p $RELAY_DIR")
    # Ensure the relay directory exists (root-owned; sudo tee writes into it).
    exec sudo -n mkdir -p "$RELAY_DIR"
    ;;
  "sudo -n tee"* | "sudo tee"*)
    # Stream a docker-save tar into the relay dir: sudo -n tee $RELAY_DIR/<file> >/dev/null
    f="${orig#*tee }"
    f="${f%% *}"
    case "$f" in
      "$RELAY_DIR"/*.tar.gz | "$RELAY_DIR"/*.tar)
        exec sudo -n tee "$f" >/dev/null
        ;;
      *)
        echo "relay: tee path not allowed: $f" >&2
        exit 1
        ;;
    esac
    ;;
  "sudo -n docker load -i"* | "sudo docker load -i"* | "docker load -i"*)
    # Load an image from a pre-streamed tar.
    f="${orig#*load -i }"
    f="${f%% *}"
    case "$f" in
      "$RELAY_DIR"/*.tar.gz | "$RELAY_DIR"/*.tar)
        exec sudo -n docker load -i "$f"
        ;;
      *)
        echo "relay: load path not allowed: $f" >&2
        exit 1
        ;;
    esac
    ;;
  "sudo -n rm -f"* | "sudo rm -f"*)
    # Delete a consumed tar from the relay dir.
    f="${orig#*rm -f }"
    f="${f%% *}"
    case "$f" in
      "$RELAY_DIR"/*)
        exec sudo -n rm -f "$f"
        ;;
      *)
        echo "relay: rm path not allowed: $f" >&2
        exit 1
        ;;
    esac
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
