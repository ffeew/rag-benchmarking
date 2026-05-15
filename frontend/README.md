# Frontend

Operator workspace for the SEC filings RAG benchmark — datasets, document ingestion, query workspace with citations and traces, evaluation runs, and system status. See ADR-0010 (`docs/adr/0010-frontend-application.md`) for the architecture decision; this README only covers running the SPA itself.

## Stack

- React 19 + Vite + TypeScript.
- TanStack Router (file-based routing under `src/routes/`) and TanStack Query for API state.
- Tailwind CSS 4 + shadcn/ui (Radix primitives) + lucide-react icons.
- React Hook Form + Zod for forms and schema validation.
- Vitest + Testing Library for unit tests.

## Local Development

```bash
pnpm install
pnpm dev
```

The dev server runs on `http://localhost:3000`. It expects the FastAPI backend at the URL defined by `VITE_API_BASE_URL` (default in `.env`/Vite config) — bring it up with `docker compose up --build` from the repo root, or run the backend directly per `backend/README.md`. The auth screen accepts the same Bearer token configured in `backend/.env`.

## Build

```bash
pnpm build
```

Outputs to `frontend/dist/`. In production the FastAPI app serves the built SPA via the path in `FRONTEND_DIST_PATH` (see `backend/rag_benchmarking/main.py`), so no separate web server is required.

## Lint, Format, Type Check

```bash
pnpm lint       # eslint (tanstack/eslint-config)
pnpm format     # prettier --write . && eslint --fix
pnpm check      # prettier --check .
pnpm test       # vitest run
```

## Route Map

Routes live under `src/routes/` and use TanStack Router's file-based conventions. Key pages:

- `datasets.index.tsx` — dataset list and creation.
- `datasets.$datasetId.documents.tsx` and the nested `documents.$documentId.{extracted,original}.tsx` viewers — document inventory and parser artifact inspection.
- `datasets.$datasetId.ingestion.tsx` — register/upload corpora, launch and monitor ingestion jobs.
- `datasets.$datasetId.query.tsx` — query workspace with filters, citations, evidence panel, and trace deep-link.
- `datasets.$datasetId.evaluations.{index,$evalRunId,compare}.tsx` — eval run creation, results, and side-by-side comparison.
- `datasets.$datasetId.eval-cases.tsx` — gold case management.
- `traces.{$traceId}.tsx` — full trace viewer (plan, retrieval candidates, verifier result, evidence, model metadata, costs).
- `jobs.{index,$jobId}.tsx` — job queue overview and detail.
- `system.tsx` — provider health and service status.

Components are grouped by feature under `src/components/`; reusable primitives live in `src/components/ui/`. API access goes through the typed client in `src/lib/api.ts`; cross-cutting providers (theme, toast, bearer token) live in `src/providers/`.

## Adding Shadcn Components

```bash
pnpm dlx shadcn@latest add <component>
```
