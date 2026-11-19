#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 24.04 server for ScrapTrust open testing (run as root, from the unpacked bundle).
#   bash deploy/server_setup.sh            -> installs Docker, firewall, settings, builds and starts the stack
# Site address: https://<server-ip-with-dashes>.sslip.io (free wildcard DNS, so no domain is needed; Caddy gets a
# real HTTPS certificate for it automatically). Settings are written to deploy/.env.production (secret, never copied off).
set -euo pipefail
cd "$(dirname "$0")/.."

IP=$(curl -fsS https://api.ipify.org || hostname -I | awk '{print $1}')
DOMAIN="${IP//./-}.sslip.io"

echo "== packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq docker.io docker-compose-v2 ufw >/dev/null
systemctl enable --now docker

echo "== firewall: only SSH and the web"
ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

echo "== settings"
if [ ! -f deploy/.env.production ]; then
  SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
  cat > deploy/.env.production <<EOF
BMTL_DOMAIN=${DOMAIN}
AUTH_MODE=public_demo
PUBLIC_RECORDS=true
SECRET_KEY=${SECRET}
COOKIE_SECURE=true
CORS_ORIGINS=[]
COPILOT_PROVIDER=offline
DEBUG=false
EXPOSE_API_DOCS=false
ALLOW_LINK_FETCH=true
MAX_REQUEST_MB=95
USER_STORAGE_QUOTA_MB=200
RECORDS_RETENTION_DAYS=0
SESSION_RETENTION_DAYS=60
WEB_CONCURRENCY=2
APP_MEM_LIMIT=12g
EOF
  chmod 600 deploy/.env.production
fi

echo "== build and start (first build downloads the AI models: 10-20 minutes)"
docker compose -f deploy/docker-compose.yml --env-file deploy/.env.production up -d --build

echo "== done: https://${DOMAIN}"
