FROM oven/bun:1.2.21

WORKDIR /app
COPY package.json bun.lock bunfig.toml ./
RUN bun install --frozen-lockfile
COPY . .
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN bun run build

ENV HOST=0.0.0.0
ENV PORT=3000
EXPOSE 3000
CMD ["bun", "serve.mjs"]
