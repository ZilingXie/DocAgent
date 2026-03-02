# Doc Agent (CLI First)

CLI-first scaffold for an Agora documentation QA agent using LangChain, Chroma, OpenAI, and a Web UI.

## Deployment Plan

- Web UI + EC2 deployment roadmap: `docs/WEB_UI_EC2_DEPLOY_PLAN.md`
- EC2 deployment runbook: `docs/EC2_WEB_DEPLOYMENT.md`

## Prerequisites

- Python 3.10 - 3.13 (3.14 currently not supported by Chroma dependency stack)
- OpenAI API key

## Setup

```bash
py -3.13 -m venv .venv313
.venv313\Scripts\python -m pip install -e .
```

Create `.env` (or update `.env.example`) and set:

```env
OPENAI_API_KEY=your_api_key
OPENAI_CHAT_MODEL=choose your model
OPENAI_EMBEDDING_MODEL=text-embedding-3-large
DOCS_DIR=doc
CHROMA_PERSIST_DIR=data/chroma/agora_docs_v1
CHROMA_COLLECTION=agora_docs_v1
RETRIEVAL_TOP_K=8
RERANK_TOP_N=6
QUERY_VARIANTS=3
RETRY_MAX_ATTEMPTS=3
RETRY_BASE_SECONDS=0.8
LOG_LEVEL=INFO
LOG_FILE=logs/doc_agent.log
WEB_HOST=0.0.0.0
WEB_PORT=8000
WEB_SESSION_WINDOW=20
WEB_ADMIN_TOKEN=
```

## CLI Commands

```bash
doc-agent init
doc-agent config
doc-agent ingest --docs-dir doc --incremental
doc-agent ingest --docs-dir doc --reset
doc-agent ask --q "How to join a channel on Android?" --platform android --product video-calling
doc-agent chat --platform android --product video-calling
doc-agent eval --dataset eval/questions.jsonl --platform android --product video-calling
doc-agent stats
```

## Web UI (Local)

```bash
doc-agent-web
```

Then open `http://localhost:8000`.

UI behavior:

- Single chat flow with only `Send` and `Reset Session` actions.
- Keeps up to 20 rounds of conversation context per session.
- Citations are rendered as clickable links and shown with each assistant reply.

Main API endpoints:

- `GET /api/health`
- `POST /api/ask`
- `POST /api/chat`
- `POST /api/chat/reset`
- `GET /docs/{path}` for opening cited markdown sources
- `POST /api/admin/ingest` (requires `WEB_ADMIN_TOKEN`)

## Docker (Local / Server)

```bash
docker compose build
docker compose up -d
docker compose logs -f
```

`eval` expects JSONL lines like:

```json
{"question":"How do I join a channel on Android?"}
```

Acceptance check:

```bash
python scripts/run_acceptance.py --dataset eval/questions.jsonl --max-questions 10
```

Incremental index script:

```bash
python scripts/rebuild_index.py
python scripts/rebuild_index.py --reset
python scripts/rebuild_index.py --full
```

Run unit tests:

```bash
python -m unittest discover -s tests -v
```

## Notes

- `ingest` is implemented with markdown loading, front matter parsing, chunking, embedding, and Chroma persistence.
- `ingest` supports incremental update mode by document hash delta.
- `ask/chat/eval` support metadata filtering (`platform`, `product`), multi-query retrieval, RRF fusion, rerank, and strict citation output.
- Runtime includes retry strategy and file logging (`logs/doc_agent.log`).
