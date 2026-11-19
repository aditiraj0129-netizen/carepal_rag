# CarePal Assist — frontend

React 18 + Vite + TypeScript + Tailwind CSS. Talks to the FastAPI backend in `../backend` (no mock data anywhere).

## Run
    # terminal 1: backend
    cd backend && .venv/bin/uvicorn app.api.main:app_factory --factory --port 8000
    # terminal 2: frontend (dev server proxies /api/* to http://127.0.0.1:8000, so no CORS setup)
    cd frontend && npm install && npm run dev        # http://localhost:5173
    npm run build                                     # production bundle in dist/ (serve behind a proxy that maps /api to the backend)

Routes: `/` chat, `/#/admin` dashboard (sign in with the backend's `ADMIN_API_KEY`; kept in sessionStorage only).

## Tests
    npm test            # vitest: phone/name validation, SSE parser
    npm run typecheck
    # browser tests (Playwright, python): need backend + dev server running
    ADMIN_API_KEY=<your key> python e2e/run.py desktop ./shots   # also: mobile
    python e2e/errors.py ./shots

## What is real
- Chat uses `POST /chat/stream` (SSE); citations, feedback (`/feedback`), escalation (`/support/escalate`), health (`/health`).
- Dashboard uses `/admin/analytics`, `/admin/unanswered`, `/admin/support-requests`, `/admin/ingest`, `/evaluation/run`.
- Chat history is stored in this browser's localStorage (the backend keeps only redacted logs, by design).
- Source preview shows the retrieved chunk text; a badge says whether it is crawled site text or a demo snapshot summary.
- Escalation confirmation text is rendered verbatim from the server, which says nobody is notified automatically.
