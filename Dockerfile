# syntax=docker/dockerfile:1

# 1. Build the web app.
FROM node:26-slim AS web
RUN npm install --global pnpm@12.0.0
WORKDIR /src
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY web/package.json web/
COPY packages/api-client/package.json packages/api-client/
RUN pnpm install --frozen-lockfile
COPY packages/api-client packages/api-client
COPY web web
RUN pnpm --filter web build

# 2. Install the server and its dependencies into a virtualenv.
FROM python:3.12-slim AS server
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY server ./
RUN uv sync --frozen --no-dev --no-editable

# 3. Runtime: Python, the virtualenv, and the built web app; no build tools.
FROM python:3.12-slim
RUN useradd --system --uid 1000 --home-dir /data iwanttowatch \
    && mkdir /data && chown iwanttowatch:iwanttowatch /data
COPY --from=server /app/.venv /app/.venv
COPY --from=web /src/web/dist /app/web
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    IWANTTOWATCH_DATA_DIR=/data \
    IWANTTOWATCH_STATIC_DIR=/app/web
USER iwanttowatch
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4)"]
CMD ["iwanttowatch", "serve"]
