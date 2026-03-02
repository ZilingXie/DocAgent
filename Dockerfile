FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY app ./app
COPY scripts ./scripts
COPY doc ./doc
COPY docs ./docs

RUN python -m pip install --upgrade pip \
    && python -m pip install -e .

EXPOSE 8000

CMD ["doc-agent-web"]
