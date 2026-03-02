#!/usr/bin/env bash
set -euo pipefail

sudo apt-get update
sudo apt-get install -y \
  docker.io \
  docker-compose-plugin \
  nginx \
  certbot \
  python3-certbot-nginx \
  git

sudo systemctl enable --now docker
sudo systemctl enable --now nginx

# Allow current user to run docker without sudo after re-login.
sudo usermod -aG docker "$USER"

echo "Bootstrap complete. Re-login to apply docker group changes."
