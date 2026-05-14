FROM node:24-alpine

WORKDIR /app/frontend

RUN npm install -g pnpm@10

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

EXPOSE 3000

CMD ["pnpm", "dev", "--host", "0.0.0.0"]
