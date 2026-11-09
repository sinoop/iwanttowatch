# Contributing to iWantToWatch

Thanks for helping! The roadmap is in the [README](README.md#roadmap), and the detailed plan in [docs/plan.md](docs/plan.md).

## How changes land

Everyone works in this repository, in parallel, on branches; `main` only changes through pull requests.

1. **Start from an issue** for anything bigger than a small fix, so two people don't build the same thing and the approach is agreed before the code.
2. **Make a branch from the latest `main`.** With write access, push it to this repository; otherwise fork it and push to your fork. Name it after the change, such as `trakt-import` or `fix-webhook-token`.
3. **Keep each pull request to one change.** Smaller pull requests are reviewed sooner and conflict less with others' work. When `main` moves on, update your branch from it.
4. **Open a pull request** early as a draft if you want feedback. Its title becomes the commit message on `main`, so describe what changes for the people using iWantToWatch.
5. **Merge once the checks pass and a maintainer approves.** Pull requests are squashed into one commit and the branch is deleted.

`main` is always releasable: every merge automatically increments the patch version, creates a `vX.Y.Z` GitHub release, and publishes the matching Docker image (`latest`, `X.Y.Z`, and `X.Y`). To bump the minor or major version, update `version` in `server/pyproject.toml` in your pull request.

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

Run these before opening a pull request; CI runs the same ones on every pull request.

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

Review the generated file; the server applies migrations on startup. If someone else's migration lands on `main` first, regenerate yours on top of it so there is one chain of migrations.

## Updating the plan

`docs/plan.md` lists each phase's milestones. Tick off or add the milestone your change delivers in the same pull request.

## Licence

By contributing, you agree that your contributions are licensed under the [AGPL-3.0-or-later](LICENSE), the same licence as the project. See [TRADEMARK.md](TRADEMARK.md) for use of the iWantToWatch name and logo.
