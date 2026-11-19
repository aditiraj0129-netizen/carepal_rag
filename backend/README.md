# CarePal Assist — backend

FastAPI + ChromaDB (dense) + own BM25 index + own RRF + grounded generation + SQLite.

## Run
    python -m venv .venv && .venv/bin/pip install -e ".[dev]"
    cp .env.example .env            # set ADMIN_API_KEY; never commit .env
    .venv/bin/python -m app.cli ingest --source snapshots     # offline seed snapshots (research summaries)
    .venv/bin/python -m app.cli ingest --source crawl         # REAL crawl of thecarepal.com (robots.txt enforced)
    .venv/bin/python -m app.cli ask "What is the refund policy?"
    .venv/bin/uvicorn app.api.main:app_factory --factory --port 8000
    .venv/bin/python -m pytest

For real semantic + Hindi/Hinglish retrieval install the `embeddings` extra and set
`EMBED_BACKEND=sentence_transformers` (multilingual-e5), then re-ingest with `--force`.
For an LLM set `LLM_PROVIDER=openai_compat` plus `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`.
LangSmith: `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` (all payloads PII-redacted).

## Honest limitations
- Escalation requests are only stored in SQLite; nobody is notified. No Firebase/CRM integration.
- Seed snapshots are paraphrased research summaries, not scraped text (`provenance` says so per citation).
- The offline hashing embedder is neither semantic nor cross-lingual; the LLM, LangSmith and HF model paths are untested live.
