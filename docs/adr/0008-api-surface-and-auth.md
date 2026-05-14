# ADR-0008: API Surface, Web App, And Auth

## Status

Accepted

## Context

The system needs a clear surface for document ingestion, querying, job status, and evaluation. Operators should be able to exercise the main workflows through a web application as well as direct HTTP calls. Full user management is outside the initial product scope, but unauthenticated write/admin APIs are not acceptable for a production-grade design.

## Decision

Expose a FastAPI HTTP API as the backend contract and a React/Vite web application as the primary human interface.

Protect ingest, query, evaluation, and admin endpoints with a configured Bearer token. Use Pydantic settings/secrets to validate required backend configuration at startup.

Do not implement a notebook-only interface or CLI in v1.

## API Groups

The API must include:

- Dataset management.
- Document upload/registration.
- Ingestion job creation and status.
- Query execution.
- Query trace retrieval when enabled.
- Evaluation run creation and results.
- Health and readiness checks.

The web app must include:

- Dataset and document management.
- Ingestion job launch and monitoring.
- Query workspace with citations and evidence.
- Trace viewer for retrieval/debug details.
- Evaluation run launch and result comparison.
- Basic service status/settings view.

## Consequences

- Reviewers can exercise the system through the web app, OpenAPI docs, and HTTP clients.
- Auth is simple enough for local Docker Compose while still showing a production security boundary.
- Future user/role management can be added without changing core ingestion or retrieval flows.

## Response Guarantees

Query responses must include:

- Answer text.
- Citations with document id, ticker, form type, filing date, page number, MinIO object key/version, and chunk id.
- Evidence snippets or structured evidence references.
- Trace id.
- Insufficient-evidence reason when applicable.

## Alternatives Considered

- No auth: rejected because ingestion and evaluation are admin-grade operations.
- Full user management: rejected as out of scope for v1.
- API-only: rejected because the project includes frontend technologies and needs an operator-facing workspace.

## References

- FastAPI bearer-token security primitives: https://fastapi.tiangolo.com/tutorial/security/first-steps/
