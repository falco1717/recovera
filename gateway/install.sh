#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: sudo ./gateway/install.sh --hostname updates.example.com --github-token-file /path/to/token

Installs Docker when needed, prepares deployment-local secrets, builds the
Recovera update gateway, and starts its HTTPS endpoint. Run the same command
with a different hostname at every gateway location.
EOF
}

hostname=""
token_file=""
while (($#)); do
  case "$1" in
    --hostname) hostname="${2:-}"; shift 2 ;;
    --github-token-file) token_file="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "Run this installer with sudo." >&2
  exit 1
fi
if [[ ! $hostname =~ ^[A-Za-z0-9][A-Za-z0-9.-]+$ ]]; then
  echo "A valid public DNS hostname is required." >&2
  exit 1
fi
if [[ -z $token_file || ! -f $token_file ]]; then
  echo "--github-token-file must name a readable fine-grained GitHub token file." >&2
  exit 1
fi

gateway_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$gateway_dir/.." && pwd)"
if ! command -v docker >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required." >&2
  exit 1
fi

install -d -m 0700 "$gateway_dir/config"
install -o root -g 39871 -m 0640 "$token_file" "$gateway_dir/config/github-token"
install -m 0644 "$gateway_dir/keys/recovera-gateway-access-signers" \
  "$gateway_dir/config/access-signers"
printf 'GATEWAY_HOSTNAME=%s\nRECOVERA_GATEWAY_REPOSITORY=%s\nRECOVERA_GATEWAY_CHANNELS=stable\nRECOVERA_GATEWAY_SYNC_INTERVAL=900\n' \
  "$hostname" "${RECOVERA_GATEWAY_REPOSITORY:-falco1717/recovera}" >"$gateway_dir/.env"
chmod 0600 "$gateway_dir/.env"

cd "$gateway_dir"
docker compose build --pull
docker compose run --rm --user root --entrypoint chown gateway \
  -R 39871:39871 /var/lib/recovera-gateway
docker compose up -d
ready=false
for _attempt in $(seq 1 30); do
  if docker compose exec -T gateway test -s /var/lib/recovera-gateway/channels/stable.json; then
    ready=true
    break
  fi
  sleep 2
done
if [[ $ready != true ]]; then
  docker compose logs --tail=100 gateway >&2
  echo "Gateway did not cache the stable channel within 60 seconds." >&2
  exit 1
fi
docker compose ps
echo "Recovera update gateway is starting at https://$hostname/"
echo "Health endpoint: https://$hostname/healthz"
