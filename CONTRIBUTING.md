# Contributing to iWantToWatch

Thanks for helping! iWantToWatch is early in development; the roadmap is in the [README](README.md#roadmap).

## Development setup

Requirements: [uv](https://docs.astral.sh/uv/), Node.js 26, and pnpm 12.

```sh
# API server on http://localhost:8080 (data in server/data/)
cd server
uv sync
uv run iwanttowatch serve

# Web app on http://localhost:5173, proxying /api to the server
pnpm install
pnpm dev:web
```

## Checks

Run these before opening a pull request; CI runs the same ones.

```sh
cd server
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
cd ..
pnpm lint:web && pnpm build:web
```

## Changing the API

The TypeScript client in `packages/api-client` is generated from the server's OpenAPI schema. After changing an endpoint or schema, run `pnpm gen:api` and commit the result.

## Changing the database

Add an Alembic migration for every model change:

```sh
cd server
uv run alembic revision --autogenerate -m "describe the change"
```

Review the generated file; the server applies migrations on startup.

## Licence

By contributing, you agree that your contributions are licensed under the [AGPL-3.0-or-later](LICENSE), the same licence as the project. See [TRADEMARK.md](TRADEMARK.md) for use of the iWantToWatch name and logo.
