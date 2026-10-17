#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: sudo ./gateway/install-saltbox.sh --hostname updates-a.example.com [--alias updates.example.com] [--github-token-file FILE]

Deploys the Recovera gateway behind an existing Saltbox Traefik instance.
The GitHub token is optional while the repository is public and required
before it becomes private.
EOF
}

hostname=""
aliases=()
token_file=""
while (($#)); do
  case "$1" in
    --hostname) hostname="${2:-}"; shift 2 ;;
    --alias) aliases+=("${2:-}"); shift 2 ;;
    --github-token-file) token_file="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

valid_hostname() { [[ $1 =~ ^([A-Za-z0-9][A-Za-z0-9-]{0,62}\.)+[A-Za-z0-9][A-Za-z0-9-]{0,62}$ ]]; }
if [[ $EUID -ne 0 ]]; then echo "Run this installer with sudo." >&2; exit 1; fi
if ! valid_hostname "$hostname"; then echo "A valid gateway hostname is required." >&2; exit 1; fi
for alias in "${aliases[@]}"; do
  valid_hostname "$alias" || { echo "Invalid gateway alias: $alias" >&2; exit 1; }
done
if [[ -n $token_file && ! -f $token_file ]]; then
  echo "The GitHub token file is not readable: $token_file" >&2
  exit 1
fi
command -v docker >/dev/null || { echo "Docker is not installed." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is required." >&2; exit 1; }
docker network inspect saltbox >/dev/null 2>&1 || { echo "The Saltbox Docker network is missing." >&2; exit 1; }
docker inspect traefik >/dev/null 2>&1 || { echo "The Saltbox Traefik container is missing." >&2; exit 1; }

gateway_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install -d -m 0700 "$gateway_dir/config"
if [[ -n $token_file ]]; then
  install -o root -g 39871 -m 0640 "$token_file" "$gateway_dir/config/github-token"
elif [[ ! -e $gateway_dir/config/github-token ]]; then
  install -o root -g 39871 -m 0640 /dev/null "$gateway_dir/config/github-token"
fi
chown root:39871 "$gateway_dir/config/github-token"
chmod 0640 "$gateway_dir/config/github-token"
install -m 0644 "$gateway_dir/keys/recovera-gateway-access-signers" \
  "$gateway_dir/config/access-signers"

rule="Host(\`$hostname\`)"
for alias in "${aliases[@]}"; do rule="$rule || Host(\`$alias\`)"; done
{
  printf 'RECOVERA_GATEWAY_TRAEFIK_RULE=%s\n' "$rule"
  printf 'RECOVERA_GATEWAY_REPOSITORY=%s\n' "${RECOVERA_GATEWAY_REPOSITORY:-falco1717/recovera}"
  printf 'RECOVERA_GATEWAY_CHANNELS=stable\n'
  printf 'RECOVERA_GATEWAY_SYNC_INTERVAL=900\n'
} >"$gateway_dir/.env.saltbox"
chmod 0600 "$gateway_dir/.env.saltbox"

cd "$gateway_dir"
compose=(docker compose --env-file .env.saltbox -f compose.saltbox.yaml)
"${compose[@]}" build --pull
"${compose[@]}" run --rm --user root --entrypoint chown gateway \
  -R 39871:39871 /var/lib/recovera-gateway
"${compose[@]}" up -d
"${compose[@]}" exec -T gateway /opt/recovera-gateway/recovera-gateway sync
"${compose[@]}" ps
echo "Recovera gateway is available through Saltbox Traefik at https://$hostname/"
