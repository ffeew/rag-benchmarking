# Multi-stage build for the React/Vite SPA.
#
# `dev` stage: runs `pnpm dev` against a bind-mounted source directory. Used by the
#   default docker-compose.yml for local development with hot reload.
# `builder` stage: runs `pnpm build` to produce static assets in /app/frontend/dist.
# `publisher` stage: minimal Alpine image that copies the built dist into a named
#   volume so the FastAPI image can serve it (see docker-compose.prod.yml).

FROM node:24-alpine AS base
WORKDIR /app/frontend
RUN npm install -g pnpm@10
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Dev stage: source is bind-mounted in compose; `pnpm install` re-runs to pick up
# new deps on container start.
FROM base AS dev
EXPOSE 3000
CMD ["pnpm", "dev", "--host", "0.0.0.0"]

# Builder stage: compile the SPA to static assets.
FROM base AS builder
COPY . .
RUN pnpm build

# Publisher stage: ship the built dist into a named volume. The container runs
# `cp` once and exits; the volume mount keeps the files around for the api service.
FROM alpine:3.20 AS publisher
WORKDIR /publish
COPY --from=builder /app/frontend/dist /dist
CMD ["sh", "-c", "rm -rf /publish/* && cp -a /dist/. /publish/ && echo 'SPA published to /publish'"]
