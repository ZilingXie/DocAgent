# EC2 Web Deployment Guide

## 1) Prerequisites

- Ubuntu EC2 instance with public IP (recommended: Elastic IP).
- Domain name managed in your DNS provider.
- Security Group inbound:
  - `22` (SSH)
  - `80` (HTTP)
  - `443` (HTTPS)
- Outbound internet access enabled.

## 2) DNS

Create an `A` record:

- Host: your subdomain (for example `docagent`)
- Value: your EC2 Elastic IP

Wait until DNS resolves.

## 3) Server bootstrap

On EC2:

```bash
git clone <this-repo-url> /opt/docagent
cd /opt/docagent
bash deploy/ec2/bootstrap.sh
```

Re-login (or `newgrp docker`) so docker group takes effect.

## 4) Configure environment

```bash
cd /opt/docagent
cp .env.example .env
```

Edit `.env`:

- `OPENAI_API_KEY`
- `OPENAI_CHAT_MODEL`
- `DOCS_DIR=doc`
- Optional `WEB_ADMIN_TOKEN` for protected ingest endpoint.

## 5) Deploy

```bash
cd /opt/docagent
export DOMAIN=your.domain.com
export EMAIL=you@example.com
export REPO_URL=<this-repo-url>
bash deploy/ec2/deploy.sh
```

This script will:

- Build and start containers.
- Run incremental ingest once.
- Configure Nginx reverse proxy.
- Issue HTTPS certificate with Certbot.

## 6) Verify

- Open `https://your.domain.com`.
- Check health:

```bash
curl -sS https://your.domain.com/api/health
```

## 7) Update rollout

```bash
cd /opt/docagent
git pull --ff-only
docker compose build
docker compose up -d
docker compose exec -T docagent-web doc-agent ingest --docs-dir doc --incremental
```

## Notes

- Vector index and logs persist in host folders:
  - `./data`
  - `./logs`
- Certbot auto-renew is installed by package defaults. You can verify timer/service:

```bash
systemctl list-timers | grep certbot
```
