# iWantToWatch

Self-hosted movie recommendations that learn your taste from your own history — Jellyfin, IMDb, Letterboxd, and Trakt — and only suggest films you haven't seen and can actually watch, on your Jellyfin server or your streaming subscriptions.

> **Status:** early development (Phase 1: catalog and taste import). You can create an account, connect TMDb, import your IMDb and Letterboxd ratings, and get an AI-written taste persona; recommendations are not implemented yet.

## Planned features

- **Library integration:** reads watch history, favourites, and the local library from Jellyfin, with automatic scrobbling via webhooks.
- **Taste import:** IMDb `ratings.csv`, Letterboxd export, and optional Trakt sync.
- **Taste scoring:** a Criticker-style match percentage computed from your own ratings, not generic popularity.
- **Available to watch:** filters to titles on your Jellyfin server or your subscriptions (Netflix, Prime Video, JioHotstar, …) in your region.
- **Regional cinema first-class:** multilingual metadata and models, so Malayalam, Tamil, Korean, and other films aren't drowned out by Hollywood.
- **Feedback loop:** rate, thumbs up/down, or dismiss suggestions to refine the model.
- **Your taste as a person:** an optional AI-written sketch of the imaginary person your ratings describe, using a local Ollama model or Google Gemini.
- **Private and lightweight:** one container, SQLite, no mandatory paid services; runs alongside Jellyfin on a home server or NAS.

Web app first; Android and iOS apps will use the same server API.

## Quick start (Docker)

```sh
git clone https://ampcode.com/@sinoopjoy/cine-match iwanttowatch
cd iwanttowatch
docker compose up -d
```

Open `http://<your-server>:8080` and follow the setup wizard to create the admin account. Data is stored in the `iwanttowatch-data` Docker volume.

## Project layout

| Path | What |
| --- | --- |
| `server/` | Python API server (FastAPI, SQLAlchemy, Alembic, SQLite) |
| `web/` | Web app (React, TypeScript, Vite, Tailwind) |
| `packages/api-client/` | TypeScript API client generated from the server's OpenAPI schema, shared with future mobile apps |
| `Dockerfile`, `docker-compose.yml` | Single-container deployment |

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development setup.

## Roadmap

0. **Foundations:** server, web shell, setup wizard, Docker, CI
1. **Catalog (TMDb) and IMDb/Letterboxd import** ← *current*
2. Jellyfin connection and automatic scrobbling
3. Streaming availability per region
4. Recommendation engine and discovery feed
5. Feedback loop
6. Trakt, Watchmode, optional LLM (local Ollama or Google Gemini)
7. First release (v0.1), then mobile apps

## Licence and trademark

iWantToWatch is free software: you can redistribute it and/or modify it under the terms of the [GNU Affero General Public License v3.0 or later](LICENSE). If you run a modified version as a network service, you must offer its source code to its users.

The iWantToWatch name and logo are trademarks; see [TRADEMARK.md](TRADEMARK.md) for what is allowed.
