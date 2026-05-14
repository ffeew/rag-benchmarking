# ADR-0010: Frontend Application

## Status

Accepted

## Context

The project uses React, Vite, Tailwind CSS, TypeScript, React Query, shadcn/ui, React Hook Form, and Zod. The system includes a frontend design that makes ingestion, querying, evidence inspection, and evaluation reproducible for operators.

The frontend should support the operational workflow without becoming a broad product surface or marketing site.

## Decision

Build a React + Vite + TypeScript single-page application backed by the FastAPI API.

Use:

- Tailwind CSS for styling.
- shadcn/ui for accessible, composable UI primitives.
- React Query for server state, caching, polling, and mutations.
- React Hook Form and Zod for forms and client-side validation.

Design the UI as a dense operational workspace, not a landing page. The first screen after auth should show dataset status, ingestion state, query access, and evaluation status.

Run the Vite dev server as a separate Docker Compose service for local development. For the packaged deployment, build the SPA to static assets and serve it from FastAPI so no extra production web server is required in v1.

## Required Views

The web app must include:

- Dataset overview with document counts, ingestion coverage, and parser/indexing status.
- Document upload/registration flow.
- Ingestion jobs table with progress, retries, failures, and artifact references.
- Query workspace with filters, retrieval mode, answer, citations, evidence snippets, and insufficient-evidence state.
- Trace detail view showing query plan, retrieval candidates, verification result, and final evidence.
- Evaluation dashboard with run configuration, aggregate metrics, per-case results, and ablation comparison.
- Settings/status view for backend, MinIO, Postgres, Redis/Celery, and model configuration health.

## UX Rules

- Prioritize scanability and repeated use over marketing polish.
- Use tables, tabs, filters, segmented controls, forms, dialogs, toasts, badges, skeleton loading states, and status indicators from shadcn/ui.
- Keep citations and evidence visible near the generated answer.
- Make failed ingestion and insufficient-evidence states explicit and actionable.
- Avoid nested cards, oversized hero sections, decorative backgrounds, and purely explanatory feature text.

## Consequences

- The backend API remains the stable contract and can still be evaluated without the web app.
- The frontend improves operational usability and makes traces/evals easier to inspect.
- API schemas should be mirrored or generated into Zod schemas to reduce frontend/backend drift.
- Docker Compose needs a frontend service for local development and a backend static-assets path for the packaged deployment.

## Alternatives Considered

- API-only: rejected because the project includes a frontend stack.
- Next.js: rejected because the project standardizes on React + Vite.
- Custom CSS/component system: rejected because shadcn/ui and Tailwind are already specified.

## References

- React project setup guidance: https://react.dev/learn/start-a-new-react-project
- Vite guide and React TypeScript templates: https://vite.dev/guide/
- Tailwind CSS with Vite: https://tailwindcss.com/docs
- shadcn/ui Vite installation: https://ui.shadcn.com/docs/installation/vite
- TanStack Query React docs: https://tanstack.com/query/latest/docs/react/
- React Hook Form resolvers: https://github.com/react-hook-form/resolvers
- Zod documentation: https://zod.dev/
