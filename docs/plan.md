# iWantToWatch — Web App implementation plan

**Goal:** a self-hosted, open-source service that learns your taste from Jellyfin, IMDb/Letterboxd, and Trakt, then suggests unwatched movies you can actually play tonight — on your Jellyfin server or on the streaming subscriptions you have. Web App first; the backend API is designed so the Android and iOS apps reuse it unchanged.

This file is the plan's source of truth: update it in the same commit as the work it describes. Sections 1–8 record the original design; where the code took a different path, the milestones in section 9 say so.

## 1. Key decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 + Alembic | Best ecosystem for the recommender (numpy, scikit-learn, ONNX embeddings); FastAPI emits OpenAPI, which the web and mobile clients are generated from |
| Database | SQLite (WAL mode) + `sqlite-vec` for embeddings, on a `/data` volume | Zero extra container, tiny idle footprint, easy backups. SQLAlchemy keeps PostgreSQL possible later, but v1 ships SQLite only |
| Background jobs | APScheduler inside the API process | No Redis/Celery/worker container; jobs are small and per-household |
| Embeddings | `fastembed` (ONNX Runtime, no PyTorch) with a multilingual model such as `paraphrase-multilingual-MiniLM-L12-v2` | Runs on CPU on a NAS; multilingual so Malayalam/Tamil/Hindi overviews embed as well as English. Loaded only while a job runs, then released |
| LLM | Optional, behind one `LlmProvider` interface with two backends: **Ollama** (local sidecar, compose profile) or **Google Gemini** (API key). Never required | Used only for explanations, mood tags, and natural-language requests; the core engine works without either. Ollama keeps everything on your server; Gemini needs no local RAM/GPU but sends data to Google, so it is opt-in |
| Frontend | React + TypeScript + Vite, TanStack Query, Tailwind; built to static files served by FastAPI | One container, one port. A PWA manifest makes it installable on phones before native apps exist |
| API client | `openapi-typescript` generated client in `packages/api-client` | Shared later by the mobile apps |
| Canonical movie ID | TMDb movie ID | Jellyfin and Trakt carry it; IMDb IDs map to it through TMDb `/find` |
| Container base | `python:3.12-slim` (Debian), multi-arch amd64 + arm64 | Alpine (musl) lacks prebuilt wheels for numpy/onnxruntime, which makes builds slow and images larger. Debian slim satisfies the requirement |
| Auth | Sign in with Jellyfin credentials (server-side `AuthenticateByName`), plus a local admin account | Household users map 1:1 to Jellyfin users with no extra passwords |

**Target footprint:** under 150 MB RAM and near-zero CPU at idle without Ollama; image under 400 MB including the embedding model.

## 2. Repository layout

```text
iwanttowatch/
  server/                    FastAPI app (package: iwanttowatch, src layout)
    src/iwanttowatch/
      api/                   REST routes under /api/v1
      db.py                  models (split into a package as it grows)
      migrations/            Alembic, applied on startup
      connectors/            jellyfin/, tmdb/, trakt/, watchmode/, imports/ (imdb, letterboxd)
      catalog/               title metadata, ID matching, caching
      recommender/           features, embeddings, models, candidates, ranking, eval
      jobs/                  scheduler + job definitions
    tests/                   pytest; recorded HTTP fixtures (respx)
  web/                       React app
  packages/api-client/       generated TypeScript client
  Dockerfile, docker-compose.yml   at the root, so `docker compose up` works from a clone
  docs/                      this plan, plus setup guides (Jellyfin webhook, TMDb key, imports)
```

The code ended up flatter: one module per concern under `src/iwanttowatch/` (see `AGENTS.md`).

## 3. Data model (SQLite)

| Table | Purpose / key columns |
| --- | --- |
| `users` | id, display\_name, jellyfin\_user\_id, region (e.g. `IN`), preferred\_languages, is\_admin |
| `titles` | tmdb\_id (PK), imdb\_id, title, original\_title, original\_language, spoken\_languages, origin\_countries, year, runtime, genres, keywords, top cast, directors/writers, overview (+ translated overviews), vote stats, popularity, poster\_path, fetched\_at |
| `title_embeddings` | `sqlite-vec` virtual table: tmdb\_id → vector, model\_version |
| `ratings` | user\_id, tmdb\_id, source (`imdb`, `letterboxd`, `trakt`, `app`, `jellyfin`), raw\_value, value\_10 (normalised 0–10), rated\_at. One effective rating per user/title: latest explicit wins |
| `watch_events` | user\_id, tmdb\_id, source, watched\_at, completion\_pct |
| `library_items` | jellyfin\_item\_id, tmdb\_id, library\_id, visible\_to (users), added\_at, removed\_at |
| `availability` | tmdb\_id, region, provider\_id, monetization (`flatrate`, `free`, `ads`, `rent`, `buy`), fetched\_at |
| `providers` / `user_subscriptions` | provider catalogue per region (from TMDb) and each user's active subscriptions |
| `feedback` | user\_id, tmdb\_id, kind (`up`, `down`, `dismiss`, `snooze`, `seen`), created\_at |
| `scores` | user\_id, tmdb\_id, score, match\_pct, reasons (JSON), model\_version, computed\_at — the precomputed feed |
| `import_jobs` / `import_rows` | uploaded CSVs, per-row match status, review queue for ambiguous rows |
| `api_cache` | key (method + normalised URL), body (compressed), etag, fetched\_at, expires\_at |
| `sync_state` / `job_runs` | per-connector cursors, last success/error, durations — shown on a Status page |

## 4. Connectors

### Jellyfin (primary, zero manual logging)

- **Setup:** admin enters server URL and an API key (Dashboard → API Keys). Each person links their Jellyfin user by signing in to Jellyfin once in Settings, or gets an account by signing in to iWantToWatch with Jellyfin credentials.
- **Initial sync:** per user, page through `/Items` with `IncludeItemTypes=Movie`, `Recursive=true`, `Fields=ProviderIds,...` to get the library that user can see plus `UserData` (Played, PlayCount, LastPlayedDate, IsFavorite, PlayedPercentage).
- **Live updates:** the official Webhook plugin with a Generic destination and "Send All Properties" posting to `/api/v1/webhooks/jellyfin?token=…`. A webhook only names the user and item; that item is then re-read from Jellyfin. Item Added/Deleted trigger a full sync.
- **Reconcile poll:** a full library read every 30 minutes and on startup (a few requests per user even for thousands of films), so no incremental cursor is needed. Webhooks are an accelerator; the poll alone guarantees correctness if a webhook is missed.
- **Signals produced:** watched → exclude + weak positive; favourite → strong positive; abandoned under 20% → weak negative; in library → "On Jellyfin" availability.

### TMDb (metadata, candidates, availability)

- Each self-hoster supplies their own free TMDb API key in the setup wizard. Show the required TMDb attribution.
- Details fetched with `append_to_response=credits,keywords,translations,alternative_titles,external_ids` in one call per title.
- **Availability:** `/movie/{id}/watch/providers` per region (data is from JustWatch; **JustWatch attribution is mandatory** or TMDb may revoke the key). Store only `flatrate`/`free`/`ads` for the strict filter; `rent`/`buy` shown as secondary info.
- **Provider list:** load `/watch/providers/movie?watch_region=XX` and let users pick their services. Do not hard-code IDs (e.g. Netflix 8, Prime Video 119, JioHotstar 2336 today), and group "channel" variants (e.g. Prime Video Channels) under their parent.

### Imports: IMDb and Letterboxd

- **IMDb `ratings.csv`:** parse `Const` (tt-ID), `Your Rating`, `Date Rated`; map via TMDb `/find/{imdb_id}?external_source=imdb_id`. Expect \~100% matches. Column names have changed over time, so parse headers by name, tolerate extra columns, and keep a fixture per known variant.
- **Letterboxd export ZIP:** `ratings.csv` (0.5–5 stars → ×2), `watched.csv`, `diary.csv`, `likes/films.csv`. Rows have Name + Year only, so match with TMDb search on title + year (±1), scoring against original and alternative titles; low-confidence rows go to a review queue in the UI.
- Re-importing is idempotent (upsert on user + title + source).
- **Automated IMDb sync:** IMDb has no public API, so scraping is out of scope. Users who run IMDB-Trakt-Syncer get IMDb data in automatically via the Trakt connector.

### IMDb ratings (optional, public opinion)

- IMDb's non-commercial datasets include `title.ratings.tsv.gz`: every title's weighted rating and vote count, refreshed daily, free for personal and non-commercial use. No API key.
- On the films iWantToWatch knew about on 2026-11-06, IMDb had 52× more votes than TMDb (median 7,912 vs 151), and 158× more for Malayalam films (6,652 vs 42). TMDb's few votes let a few hundred fans rate a film 8.8 that IMDb rates 6.7.
- An admin turns it on in Settings, which notes IMDb's non-commercial terms. Feed builds download the file at most once every 20 hours and copy the rating and vote count of films in the catalogue; turning it off removes them. The UI credits IMDb while it's on.

### Trakt (optional)

- OAuth device-code flow; each self-hoster registers their own Trakt app (Standard API tier is free).
- Pull `/sync/history/movies`, `/sync/ratings/movies`, `/sync/watched/movies`; use `/sync/last_activities` to skip unchanged data. Respect rate limits (authenticated GET: 500 per 5 min) and `Retry-After`.
- **Caveat:** since July 2026, free Trakt accounts can connect only one Community App. Users already using Trakt with another app (e.g. a Jellyfin Trakt plugin) would need VIP, so iWantToWatch also accepts a **Trakt data export** file as a one-time import. Jellyfin stays the primary live source.

### LLM providers (optional): Ollama or Gemini

- **One interface, two backends.** Recommender code calls `LlmProvider.generate(prompt, json_schema)` and never knows which backend answers. Settings offers None / Ollama (base URL + model) / Gemini (API key + model), with a "Test connection" button.
- **Gemini:** calls the Gemini REST API with the user's own key from Google AI Studio and requests structured JSON output. The model name is configurable rather than hard-coded, since Google renames models often. Its free tier has rate limits, so calls go through the same rate limiter, backoff, and circuit breaker as other connectors.
- **Privacy:** prompts contain only title metadata and an aggregated taste summary (e.g. top genres, languages, people), never usernames, Jellyfin URLs, or raw watch history. The Settings page states that Gemini sends this data to Google.
- **Cost control:** results are cached in the DB per title and prompt version, so mood tags and explanations are generated once, not on every page view.
- **Embeddings stay local** (`fastembed`) for both choices. Switching to Gemini embeddings would mean re-embedding the whole catalogue in a different vector space, so it is not part of v1.

### Other availability sources (adapters, off by default)

- **Watchmode:** optional adapter behind the same `AvailabilityProvider` interface for users who want a second source; quota-limited free tier, so only refresh titles shown in the feed.
- **JustWatch direct:** no official public API; not shipped. The adapter interface lets the community add one at their own risk.

## 5. Resilience and caching

- One shared HTTP client per connector with: `api_cache` lookups (TTL per endpoint: title details 30 days, credits/keywords 30 days, watch providers 3 days, discover pages 24 h), conditional requests with ETag where supported, a per-host token bucket and concurrency cap, exponential backoff honouring `Retry-After` on 429/5xx, and a circuit breaker that pauses a failing connector.
- On failure the UI serves the last good data and marks it stale; the Status page shows each connector's last success and error.
- Before a title with stale availability (older than its TTL) appears in the feed, it is rechecked in the background; if the check fails it keeps its last known badge with a "checked N days ago" note.
- Posters are lazily cached to `/data/posters` (w342 size, capped disk usage).
- Nightly SQLite online backup to `/data/backups` (keep 7).

## 6. Recommendation engine

### Labels: turning signals into taste

- Normalise every explicit rating to 0–10, then convert to the user's own **percentile** (Criticker-style), so a generous rater and a harsh rater are comparable and "match %" means "predicted to land in your top X%".
- Implicit signals become low-weight pseudo-labels: favourite ≈ 85th percentile, thumbs-up ≈ 80th, completed but unrated ≈ 60th, thumbs-down ≈ 20th, abandoned ≈ 30th. Explicit ratings always override.

### Features per title

- **Multilingual text embedding** of title, original title, overview, tagline, genres, and keywords.
- **Structured sparse features:** genres, TMDb keywords, directors, writers, top-billed cast, composer, original language, origin country, decade, runtime bucket.
- **Weak priors:** Bayesian-averaged vote and log popularity — normalised **within each original language**, so a well-loved Malayalam film with 300 votes is not treated as obscure next to a Hollywood film with 30,000. The vote is IMDb's when IMDb ratings are on, otherwise TMDb's.

### Candidate generation (nightly + on demand)

Union, de-duplicated, minus already-excluded titles, capped at a few thousand per user:

1. Unwatched movies in the user's Jellyfin libraries.
2. TMDb Discover per subscribed provider (`with_watch_providers`, `watch_region`, `with_watch_monetization_types=flatrate|free|ads`), across the user's languages, sorted by vote average with a per-language vote-count floor.
3. TMDb recommendations/similar for the user's top-rated \~50 titles.
4. Per-language discovery for every language that appears in the user's ratings or settings, so regional cinema is always represented.
5. When an LLM is configured: films it suggests from the user's taste summary, including what they liked or disliked about films in their own words.

### Scoring model (v1, per user, CPU-only)

- **Neighbour score:** for each candidate, the similarity-weighted average percentile of the user's k (≈20) most similar rated films in embedding space. Explainable: "because you rated *Kumbalangi Nights* 9 and *Maheshinte Prathikaaram* 8".
- **Feature score:** a ridge regression on the sparse features trained on the user's labels; learns things like "likes Fahadh Faasil and Dileesh Pothan, dislikes slasher horror".
- **Blend:** weights chosen per user by cross-validation; with few ratings (under \~30) the blend leans on language/genre preferences and quality priors (cold start).
- **Match %:** predicted percentile, calibrated on held-out ratings.
- **Retraining:** full rescoring nightly; after feedback, a debounced (\~30 s) background rescore of that user. Both models train in well under a second for thousands of ratings.

### Filtering, ranking, explanations

- **Hard exclusions:** watched or rated in any source, dismissed, or snoozed (until the snooze ends).
- **"Available only" toggle (default on):** keep a title only if it is in a Jellyfin library visible to the user **or** has a `flatrate`/`free`/`ads` offer on one of the user's subscriptions in their region.
- **Diversity:** MMR re-ranking on embeddings, so the top 20 is not ten near-identical films; optional language mix control.
- **Mood tags:** a curated mapping from TMDb keywords to a small mood vocabulary (feel-good, dark, slow-burn, mind-bending, family, thrilling…); the configured LLM (Ollama or Gemini) can refine tags when enabled.
- **Evaluation:** `iwanttowatch eval` holds out 20% of a user's ratings and reports Spearman correlation and NDCG@20 against a popularity baseline, so contributors can compare models objectively.

### Later model upgrades (not v1)

- Household collaborative filtering once several users have ratings.
- Optional user-downloaded MovieLens data for item-item CF (its licence forbids redistributing it, so it cannot ship in the image).
- LLM re-ranking of the top 100 with the configured LLM (Ollama or Gemini), for natural-language requests like "something light and Malayalam tonight".

## 7. Web App

| Screen | Contents |
| --- | --- |
| Setup wizard (first run) | TMDb key, Jellyfin URL + API key, default region, admin account; tests each connection |
| Discovery feed | Cards: poster, title + original title, year, language, **match %**, availability badges (On Jellyfin, On Netflix, On Prime Video, On JioHotstar), genre and mood tags, one-line reason. Actions: 👍 👎 rate (1–10) · dismiss · seen it. Filters: available-only toggle, providers, languages, genres, runtime, decade |
| Title detail | Overview, cast/crew, where to watch (with JustWatch attribution), "Play on Jellyfin" deep link, why it was suggested |
| My taste | Rating history by source, imports, review queue for unmatched rows, top genres/languages/people learned |
| Settings | Region, subscriptions, languages, connectors (Jellyfin, Trakt, Watchmode), LLM provider (None / Ollama / Gemini), data export |
| Status | Connector health, last sync, job history, cache stats |

**API (REST, `/api/v1`):** `auth/*`, `me`, `settings`, `imports` (upload, status, review), `ratings`, `feed` (paginated, filter params), `titles/{tmdb_id}`, `feedback`, `connectors/*`, `webhooks/jellyfin`, `status`. The feed reads from the precomputed `scores` table, so it stays fast on slow hardware.

## 8. Deployment

- One image, `iwanttowatch`, built in two stages: Node builds `web/`, then a `python:3.12-slim` runtime with the static files and the embedding model baked in. Runs a single uvicorn worker as a non-root user, with a `/healthz` healthcheck.
- `docker-compose.yml`: the `iwanttowatch` service with a `./data:/data` volume and port 8080; an `ollama` service behind a `llm` profile.
- Configuration: a few env vars (`IWANTTOWATCH_SECRET_KEY`, `IWANTTOWATCH_BASE_URL`); everything else via the setup wizard, stored in the DB with secrets encrypted by the secret key.
- Publish multi-arch images (amd64, arm64) on each tagged release.

## 9. Milestones

Each phase ends in something runnable in Docker.

### Phase 0 — Foundations

- [x] Monorepo scaffold, AGPL-3.0-or-later licence, trademark policy, contributing guide, CI (ruff, mypy, pytest, oxlint, tsc, API-client drift check, Docker build)
- [x] FastAPI skeleton, SQLite + Alembic, settings, local admin auth, setup wizard (admin account, region, languages)
- [x] React shell, generated API client, Dockerfile + compose

**Exit:** `docker compose up` serves the wizard; idle RAM measured and recorded. **Met** 2026-11-05: container healthy, about 59 MiB RAM and 0.2% CPU at idle, 245 MB image.

### Phase 1 — Catalog and taste import

- [x] TMDb client with cache, rate limiter, backoff
- [x] Title model + metadata fetch, multilingual fields
- [x] IMDb and Letterboxd import, matching, review queue, My taste page

Built and tested against a fake TMDb on 2026-11-06. The exit criterion still needs a real TMDb key and real exports.

**Exit:** a real IMDb export of 1,000+ ratings imports with ≥ 99% auto-matched; a Letterboxd export with ≥ 95% auto-matched.

### Phase 2 — Jellyfin

- [x] Connector, user linking, Jellyfin login
- [x] Library + watched/favourite sync, webhook endpoint, reconcile poll; sync status shown in Settings instead of a separate Status page

**Exit:** finishing a movie in Jellyfin marks it watched within a minute with the webhook, or within 30 minutes without it. **Met** 2026-11-06: against a real Jellyfin 12.4 with Webhook plugin v22, a playback stop showed as watched in 0.25 s; with the webhook failing, the next full sync caught up.

### Phase 3 — Availability

- [x] Provider catalogue per region, subscription settings (per person: country and services)
- [x] Per-title availability cache (3 days, last good data kept and marked stale on failure), badges on My taste, JustWatch attribution. Rechecks happen when titles are shown; Phase 4 adds the background refresh for feed candidates.

Built and tested against a fake TMDb on 2026-11-06; channel variants are listed separately rather than grouped. The exit criterion still needs a real TMDb key.

**Exit:** badges for a sample of 50 titles in region IN match TMDb's watch pages.

### Phase 4 — Recommender v1 and Discovery feed

- [x] Features (TF-IDF over genres, keywords, people, language, decade), candidate generation, neighbour + ridge models with a per-language quality prior, cross-validated blend and calibration. Embeddings are deferred: the neighbour model uses the sparse features for now, which keeps the image small
- [x] Filters (available only, language, genre), MMR, reasons, mood tags; feed and title detail UI with "Play on Jellyfin" and rate-from-detail
- [x] `iwanttowatch eval <username>`: Spearman and NDCG@20 against a popularity baseline
- [x] Faster page loads (2026-11-06): gzip for text responses, hashed assets cached for good, and the page preloads the setup and account requests alongside the script. At 250 ms latency the feed data arrives at 0.90 s instead of 1.48 s

Built and tested against a fake TMDb on 2026-11-06. The exit criterion still needs real ratings, a real TMDb key, and a Pi-class machine.

**Exit:** beats the popularity baseline on held-out ratings (NDCG@20); feed loads in under 300 ms on a Raspberry Pi 5–class machine.

### Phase 5 — Feedback loop

- [x] Netflix-style rating (Didn't like / Liked / Loved) with up to 3 tags from a fixed vocabulary — "what did you like most?" or "what didn't work?" — fed into the taste summary and persona; reactions map to the user's own 15th/65th/90th rating percentiles (pulled forward, 2026-11-06)
- [x] Thumbs, dismiss, snooze (30 days), seen-it with undo on feed cards. Thumbs are weak labels at the 80th/20th percentile; thumbs-down, dismiss and snooze hide the film; seen-it records a watch, and the undo toast also offers "Rate it"
- [x] Debounced incremental rescoring: 15 s after the last rating or feedback, the stored candidates are scored again without TMDb requests; the feed shows "Re-ranking with your feedback…" and refreshes itself
- [x] Optional birth year in Settings: films from before it lose up to 6 points of match, growing over the 30 years before the birth year, and the penalty halves after 3 liked films from before it. Never a filter; kept out of AI prompts and taste links; used per person in Watch together (added 2026-11-06)
- [x] Quality prior fix: a language with few films in the pool borrows the vote norms of all films, so a film alone in its language isn't judged against itself (2026-11-06)
- [x] IMDb ratings for quality (2026-11-06): an admin switch in Settings; the quality prior uses IMDb's rating and votes when known, and cards and title details show "IMDb 8.7". On a real feed, Facing El Chapo (TMDb 8.8 from 975 votes, IMDb 6.7 from 9,925) fell from 85% to 59%
- [x] AI picks (2026-11-06): with an LLM configured, each feed build asks it for 25 films from the taste summary, including what the user liked or disliked about films. They're matched to TMDb, scored by the same recommender with a 4-point bonus, filtered for seen films and availability like any candidate, and marked "AI pick: …" with the LLM's reason. A failed LLM call keeps the last build's picks

**Exit:** a thumbs-down visibly reorders the feed within a minute. **Met** 2026-11-06 against a fake TMDb: a thumbs-down on a Nolan film re-ranked the feed about 16 s later, and the other Nolan film dropped the most.

### Phase 5b — Watch together (group picks)

Proposed 2026-11-06: "what should we all watch next" when friends come over.

- [x] Pick who's watching on a new Watch together page: the household is every user on this server, plus guest profiles from friends on other iWantToWatch servers; a one-tap "Household" chip selects everyone at home
- [x] Shareable taste profile: a revocable link (Watch together → Share your taste) serving only TMDb IDs, how much the person liked each, and which films they've seen; no names or server details. The host refreshes a guest's copy when it's over an hour old and drops the guest when the link is revoked
- [x] Group score: each film scored for each person by the same recommender. Ordering uses the average minus a penalty when anyone falls below 60% (least misery); the card badge shows the plain average
- [x] Exclude films anyone has seen or hidden; availability is the host's Jellyfin and services
- [x] Group cards with each person's match (red below 60%) and each reason labelled with whose taste it comes from
- [ ] Taste card file for friends whose server can't be reached from yours (most home servers): the same data as the link, downloaded and sent by any messenger, uploaded under "Add a friend"; no auto-refresh

Built and tested with two instances against a fake TMDb on 2026-11-06. The exit criterion still needs real rating depth: someone with only a few ratings stays near the cold-start baseline, below 60% for most films.

**Exit:** for a group of three, every pick in the top 10 is at least a 60% match for each person.

### Phase 5c — Child profiles

Proposed 2026-11-06: parents find what their kids should watch.

- [ ] Parent-managed child profiles: created and managed by a parent; kids can't see other people's ratings
- [ ] Age limit per child as a maximum certificate (e.g. U or U/A 7+ in India, PG in the US), from TMDb's per-country certifications; films above the limit or without a certificate are left out
- [ ] Family-positive signals: TMDb keywords such as friendship, courage, and kindness; parents' "Great with family" tags; the child's own reactions
- [ ] Optional LLM-written "themes and values" note per film, labelled as AI-written (no free API rates morals: Common Sense Media and IMDb's parents' guide have no open API)
- [ ] Child profiles take part in household and Watch together picks, with the age limit applied to the whole group

**Exit:** no film above a child's certificate ever appears in their feed or in a group pick that includes them.

### Phase 6 — Optional integrations and polish

- [ ] Trakt (device flow, history/ratings pull, export-file import)
- [ ] Watchmode adapter
- [ ] Critic scores (Rotten Tomatoes, Metacritic) through OMDb with a free key; thin coverage of Indian films
- [x] LLM provider interface with Ollama and Gemini backends, tested from Settings (pulled forward, 2026-11-06)
- [x] "Your taste as a person" persona per user, rewritten after each import (pulled forward, 2026-11-06)
- [ ] LLM explanations, mood tags, natural-language requests
- [x] Per-user data export and restore (JSON with profile, ratings and watches per source, and feedback), in Settings → Your data (pulled forward, 2026-11-06)
- [ ] PWA, UI translations, server backups, docs

### Phase 7 — v0.1 release

- [ ] Install docs with screenshots, sample compose, multi-arch images, release notes

### After the Web App: mobile

The mobile apps talk to the same self-hosted API. Two routes, to decide after v0.1: **Capacitor** wrapping the web app (fastest, one codebase), or **Expo / React Native** sharing `packages/api-client` (more native feel). Both reuse the backend unchanged.

## 10. Risks

| Risk | Mitigation |
| --- | --- |
| TMDb/JustWatch availability gaps or lag for Indian services | Show "checked N days ago"; optional Watchmode adapter; user can mark "not actually on Netflix" which hides that badge |
| Letterboxd title matching for regional films (English vs. transliterated titles) | Match on original + alternative titles; review queue; remember manual fixes |
| Trakt Community App limit for free accounts | Trakt optional; export-file import; Jellyfin is the live source |
| Few ratings → weak recommendations | Cold-start onboarding: rate 20 quick picks across the user's languages before the first feed |
| Embedding model RAM spikes on small NAS | Load only during jobs, batch size limits, configurable smaller model |
| API terms (TMDb non-commercial, JustWatch attribution, IMDb datasets non-commercial) | Each user brings their own key; IMDb ratings are off until an admin turns them on; attribution built into the UI |
| Gemini cost, quota, and privacy | Optional and off by default; minimal prompts with no personal identifiers; DB caching of results; Ollama or no LLM remain full alternatives |
| LLM suggests films that don't exist or don't fit | Suggestions are only candidates: each must match a TMDb film, is scored by the recommender like any other, and is dropped if seen or unavailable |

## 11. Open questions

Decided: **AGPL-3.0-or-later plus a trademark policy** on the iWantToWatch name and logo (renamed from CineMatch on 2026-11-06). LLM: Ollama or Gemini, both optional. Public hosting: mirrored to [GitHub](https://github.com/sinoop/iwanttowatch). Assumed: household multi-user, default region India (both changeable).

1. **Trakt in v1** or deferred to Phase 6 as planned?
2. **Contributor agreement:** contributions are currently inbound=outbound AGPL. Selling commercial licences yourself later would need a CLA from contributors.
