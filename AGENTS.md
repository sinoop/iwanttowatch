# iWantToWatch

Self-hosted movie recommender: Python API server, React web app, shared generated TypeScript client.

## Layout

- `server/` — FastAPI app in `src/iwanttowatch`; engine and session in `db.py`; models in `models.py`; TMDb client in `tmdb.py`; metadata and title matching in `catalog.py`; IMDb/Letterboxd import and its background worker in `imports.py`; Jellyfin client, library sync, and its worker in `jellyfin.py`; streaming offers per region (TMDb/JustWatch) in `availability.py`; taste scoring (features, neighbour and ridge models, calibration, diversity, evaluation) in `recommender.py`; candidate gathering, feed builds, and their worker in `feed.py`; group picks and taste links in `together.py`; child profiles, per-country certificates, and themes notes in `children.py`; mood tags in `moods.py`; Ollama/Gemini providers in `llm.py`; effective ratings, taste summary, and persona in `taste.py`; database backups and their worker in `backups.py`; the fixed rating-tag vocabulary in `tags.py`; routes in `api/`; Alembic migrations in `migrations/versions/`. Tests in `server/tests`.
- `web/` — React + Vite + Tailwind; talks to the API only through `@iwanttowatch/api-client`.
- `packages/api-client/` — `openapi.json` and `src/schema.d.ts` are generated; never edit them by hand.

## Git worktree workflow

Every change must be made in its own git worktree inside `.git_worktrees/<task-name>`, never in the main checkout. Keep the main checkout on `main` so multiple people or agents can work in parallel without colliding.

1. **Create a worktree for each task** before touching any file:
   ```sh
   git worktree add .git_worktrees/<task-name> -b <task-name> main
   ```
2. **Edit and run checks only inside the worktree.** Every file path, editor action, and shell command must point at `.git_worktrees/<task-name>/...`. Before running server or web checks in a new worktree, install its local dependencies (`pnpm install --frozen-lockfile` from the worktree root and `cd server && uv sync --frozen`, or `./.agents/setup`) so workspace packages and virtualenvs resolve inside the worktree rather than the main checkout.
3. **Stage and commit selectively** from inside `.git_worktrees/<task-name>/`:
   - Never use `git add .`. Stage only the files you changed (`git add <file1> <file2>`) or specific hunks (`git add -p`).
   - Run `git add`, `git commit`, and `git push` as separate commands rather than chaining them with `&&`:
     ```sh
     git add <file1> <file2>
     git commit -m "short description"
     git push origin <task-name>
     ```
4. **Review the diff:**
   ```sh
   git diff main..<task-name>
   ```
5. **Land on `main`** via a squashed pull request or squash-merge from the main checkout (`git checkout main`, `git pull --rebase origin main`, `git merge --squash <task-name>`, `git commit -m "short description"`, `git push origin main`).
6. **Clean up** after the change lands on `main`:
   ```sh
   git worktree remove .git_worktrees/<task-name>
   git branch -D <task-name>
   ```
   Use `git worktree list` to inspect active worktrees and `git worktree prune` to clear stale entries.

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
- `docs/plan.md` is the implementation plan: update its milestones in the same commit as the work they describe.
