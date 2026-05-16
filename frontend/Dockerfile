# Multi-stage build for the React/Vite SPA.
#
# `dev` stage: runs `pnpm dev` against a bind-mounted source directory. Used by
#   the default docker-compose.yml for local development with hot reload.
# `builder` stage: runs `pnpm build` to produce static assets in
#   /app/frontend/dist.
# `publisher` stage: minimal Alpine image that copies the built dist into a
#   named volume so the FastAPI image can serve it (see docker-compose.prod.yml).

FROM node:24-alpine AS base
WORKDIR /app/frontend

# `npm install -g` (over corepack) avoids corepack's auto-update behavior,
# which can silently jump to a newer major (e.g. pnpm 11) even when the active
# version was prepared at pnpm@10 — breaking lockfile compatibility.
RUN npm install -g pnpm@10 \
 && chown -R node:node /app

# Reuse the image's uid 1000 `node` user so dev/builder never run as root.
USER node

COPY --chown=node:node package.json pnpm-lock.yaml ./

# Cache mount preserves the pnpm store across builds so a lockfile bump only
# re-resolves, not re-downloads.
RUN --mount=type=cache,uid=1000,gid=1000,target=/home/node/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

# Dev stage: source is bind-mounted in compose; the image's node_modules is
# preserved via a named volume so the bind mount doesn't shadow them.
FROM base AS dev
EXPOSE 3000
CMD ["pnpm", "dev", "--host", "0.0.0.0"]

# Builder stage: compile the SPA to static assets.
FROM base AS builder
COPY --chown=node:node . .
RUN pnpm build

# Publisher stage: ship the built dist into a named volume. The container runs
# `cp` once and exits; the volume mount keeps the files around for the api
# service. Stays as root alpine — short-lived, no network surface.
FROM alpine:3.20 AS publisher
WORKDIR /publish
COPY --from=builder /app/frontend/dist /dist
CMD ["sh", "-c", "rm -rf /publish/* && cp -a /dist/. /publish/ && echo 'SPA published to /publish'"]
