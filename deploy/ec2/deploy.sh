#!/usr/bin/env bash
set -euo pipefail

: "${DOMAIN:?Set DOMAIN, e.g. export DOMAIN=docagent.example.com}"
: "${EMAIL:?Set EMAIL, e.g. export EMAIL=ops@example.com}"
: "${REPO_URL:?Set REPO_URL, e.g. export REPO_URL=git@github.com:org/repo.git}"

APP_DIR="/opt/docagent"
BRANCH="${BRANCH:-main}"

if [[ ! -d "$APP_DIR/.git" ]]; then
  sudo mkdir -p "$APP_DIR"
  sudo chown "$USER:$USER" "$APP_DIR"
  git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
git fetch --all --prune
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo ".env not found. Created from .env.example. Fill OPENAI_API_KEY then rerun."
  exit 1
fi

docker compose build
docker compose up -d

# Optional initial index build; safe to rerun.
docker compose exec -T docagent-web doc-agent ingest --docs-dir doc --incremental || true

tmp_conf="$(mktemp)"
sed "s/__DOMAIN__/${DOMAIN}/g" deploy/nginx/docagent.conf > "$tmp_conf"
sudo cp "$tmp_conf" /etc/nginx/sites-available/docagent
rm -f "$tmp_conf"

if [[ -L /etc/nginx/sites-enabled/default ]]; then
  sudo rm -f /etc/nginx/sites-enabled/default
fi
if [[ ! -L /etc/nginx/sites-enabled/docagent ]]; then
  sudo ln -s /etc/nginx/sites-available/docagent /etc/nginx/sites-enabled/docagent
fi

sudo nginx -t
sudo systemctl reload nginx

sudo certbot --nginx \
  -d "$DOMAIN" \
  --non-interactive \
  --agree-tos \
  -m "$EMAIL" \
  --redirect

echo "Deployment complete: https://${DOMAIN}"
