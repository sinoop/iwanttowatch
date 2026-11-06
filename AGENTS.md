# iWantToWatch

Self-hosted movie recommender: Python API server, React web app, shared generated TypeScript client.

## Layout

- `server/` — FastAPI app in `src/iwanttowatch`; engine and session in `db.py`; models in `models.py`; TMDb client in `tmdb.py`; metadata and title matching in `catalog.py`; IMDb/Letterboxd import and its background worker in `imports.py`; Jellyfin client, library sync, and its worker in `jellyfin.py`; streaming offers per region (TMDb/JustWatch) in `availability.py`; Ollama/Gemini providers in `llm.py`; effective ratings, taste summary, and persona in `taste.py`; the fixed rating-tag vocabulary in `tags.py`; routes in `api/`; Alembic migrations in `migrations/versions/`. Tests in `server/tests`.
- `web/` — React + Vite + Tailwind; talks to the API only through `@iwanttowatch/api-client`.
- `packages/api-client/` — `openapi.json` and `src/schema.d.ts` are generated; never edit them by hand.

## Commands

- Server checks (from `server/`): `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
- Web checks (from the repo root): `pnpm lint:web && pnpm build:web`
- After changing API routes or schemas: `pnpm gen:api` (from the repo root) and commit the generated files.
- After changing models: `uv run alembic revision --autogenerate -m "..."` (from `server/`); `test_migrations_match_models` fails if a migration is missing.
- Full stack: `docker compose up --build`.
- LLM features are optional: code must work when `provider_from_settings` returns None. Prompts carry taste data only, never usernames or server details.
- Tests fake TMDb with `respx` (see `fake_tmdb` in `server/tests/test_imports.py`; the shared `mock` and `client` fixtures are in `conftest.py`) and Jellyfin with `FakeJellyfin` in `server/tests/test_jellyfin.py`; `IWANTTOWATCH_TMDB_BASE_URL` points the server at a local stub for manual testing.

## Conventions

- Keep the runtime to one container and SQLite; no extra services unless optional.
- Keep `openapi-typescript` on TypeScript 5 in `packages/api-client`: TypeScript 7 has no compiler JS API.
- Source files are AGPL-3.0-or-later; don't add dependencies with incompatible licences.
