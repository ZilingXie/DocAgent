# DocAgent Web UI + EC2 Deployment Plan

## Objective

Build a production-ready Web UI for DocAgent and deploy it on AWS EC2 behind a custom domain with HTTPS.

## Scope

- Keep existing CLI capabilities.
- Add a web backend API that reuses current QA/ingest logic.
- Add a browser UI for ask/chat style interaction and citation display.
- Containerize and deploy to EC2 with reverse proxy + TLS.

## Architecture (Target)

- `FastAPI` backend:
  - `POST /api/ask` for single-turn QA.
  - `POST /api/chat` for multi-turn conversation (session-based, in-memory first).
  - `GET /api/health` for health checks.
  - Optional admin endpoints: `POST /api/admin/ingest`.
- `Web UI`:
  - Minimal frontend (server-rendered template or static SPA) calling `/api/*`.
  - Show answer, latency, and citations.
- `Vector DB`:
  - Keep local Chroma persistence directory on EC2 volume.
- `Reverse Proxy`:
  - Nginx for TLS termination and domain routing.

## Milestones

### M1: Web Service Foundation

- Create `app/web/main.py` (FastAPI app factory + routes).
- Define request/response schemas (`app/web/schemas.py`).
- Reuse `app.qa.chain.answer` in API layer.
- Add health endpoint and structured error handling.

Done when:
- Local `uvicorn` starts successfully.
- `/api/health` returns 200.
- `/api/ask` returns the same core fields as CLI (`answer_text`, `citations`, `latency_ms`).

### M2: Web UI

- Add frontend page (e.g., `app/web/templates/index.html` + static assets).
- Provide:
  - Question input.
  - Optional filters (`platform`, `product`).
  - Answer area and citation list.
  - Loading/error states.
- Keep initial UI simple and stable; style polish can be a separate iteration.

Done when:
- User can complete one full QA flow in browser.
- Citations are visible and readable.

### M3: Packaging and Runtime

- Add production `Dockerfile` and `.dockerignore`.
- Add `docker-compose.yml` for local/prod-like run.
- Persist:
  - `data/chroma/*`
  - `logs/*`
- Ensure environment vars are loaded from `.env`.

Done when:
- `docker compose up -d` starts service.
- Container restart does not lose index data.

### M4: EC2 Deployment

- Provision on EC2:
  - Docker + Compose plugin.
  - Nginx + Certbot.
- Domain setup:
  - DNS `A` record -> EC2 Elastic IP.
- Security:
  - Security Group allow `22`, `80`, `443`.
  - App bound to localhost/private network; public traffic only through Nginx.
- Process:
  - Pull code, set `.env`, run ingest once, then start services.

Done when:
- `https://your-domain` opens Web UI.
- HTTPS certificate is valid.
- `/api/health` reachable through domain.

### M5: Ops and Reliability

- Add startup checks:
  - Fail fast if `OPENAI_API_KEY` missing.
  - Verify Chroma directory writable.
- Add basic observability:
  - Request logs + error logs.
  - Optional CloudWatch agent in later iteration.
- Backup and recovery:
  - Snapshot/backup strategy for `data/chroma`.

Done when:
- Service can be restarted/redeployed with repeatable steps.
- Basic failure scenarios are diagnosable from logs.

## Deployment Runbook (EC2)

1. Create/attach Elastic IP and map domain `A` record.
2. Install runtime dependencies (`docker`, `docker compose`, `nginx`, `certbot`).
3. Clone repo on EC2 and prepare `.env`.
4. Build and start app container.
5. Run initial index build (`doc-agent ingest --docs-dir doc --incremental`) inside container or one-off job.
6. Configure Nginx reverse proxy to app port.
7. Issue TLS cert (`certbot --nginx -d your-domain`).
8. Validate:
   - Browser access
   - API health
   - End-to-end ask flow
9. Set up auto-renew for certbot and restart policy for containers.

## Risks and Mitigations

- OpenAI quota or model availability:
  - Keep model fallback as currently implemented.
- Slow first response:
  - Pre-warm ingest and keep index persisted.
- Data loss on instance replacement:
  - Use EBS volume + snapshot policy.
- Prompt/API abuse:
  - Add simple rate limit at Nginx level (phase 2 hardening).

## Acceptance Checklist

- [ ] Web UI supports ask flow with citations.
- [ ] Works on domain over HTTPS.
- [ ] Zero-downtime restart for normal deploys (or < 1 minute with clear runbook).
- [ ] Logs are persisted and accessible.
- [ ] Rebuild instructions are documented and reproducible.

## Suggested Execution Order

1. M1 (API)
2. M2 (UI)
3. M3 (Docker)
4. M4 (EC2 + Domain + TLS)
5. M5 (Ops hardening)
