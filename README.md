# iWantToWatch

Self-hosted movie recommendations that learn your taste from your own history — Jellyfin, IMDb, Letterboxd, and Netflix — and only suggest films you haven't seen and can actually watch, on your Jellyfin server or your streaming subscriptions.

> **Status:** v0.1.0, the first release of the web app; see the [changelog](CHANGELOG.md). Trakt, Watchmode, critic scores, Google sign-in, and translations are still to come, and Android and iOS apps come next.

![Discover: films picked for you, with match percentages, streaming badges, and mood tags](docs/images/discover.webp)

## Features

- **Your history, imported:** IMDb `ratings.csv`, Letterboxd export, and Netflix viewing history, with a review queue for titles that don't match on their own.
- **Jellyfin, live:** watched films, favourites, and your local library sync on their own, within a second through the Webhook plugin or every 30 minutes without it. Sign in with your Jellyfin account if you like.
- **Taste scoring:** a Criticker-style match percentage from your own ratings, not generic popularity, optionally using IMDb ratings to judge quality. An optional birth year gently lowers films from long before you were born, unless you've liked films from that era.
- **Only what you can watch:** pick your country and the services you pay for (Netflix, Prime Video, JioHotstar, …); the feed shows films on them or on your Jellyfin server, with a chip per platform. Free and ad-supported services wait behind their own chip.
- **Regional cinema first-class:** multilingual metadata and per-language quality norms, so Malayalam, Tamil, Korean, and other films aren't drowned out by Hollywood.
- **Netflix-style rating:** Didn't like / Liked / Loved, with up to three tags for what worked or didn't and an optional short note.
- **Feedback loop:** thumbs up or down, "seen it", "not now", and "not interested" on each card re-rank the feed within seconds.
- **Shortlists:** save films to decide between later, on your own or as a household.
- **Watch together:** picks for everyone watching, scored for each person so nobody is likely to dislike the top picks. Friends on other servers share a revocable taste link or card; people at home without an account vote Yes, Maybe, or No from a guest link on their phone.
- **Household:** invite links for new members; parent-managed child profiles with an age limit by certificate (such as U/A 7+ or PG), a parent PIN, and family-friendly picks.
- **Optional AI** (a local Ollama model or Google Gemini, in the order you choose):
  - predicts how you'd rate the top of your feed and suggests a few films of its own;
  - answers requests such as "a light Malayalam comedy under 2 hours" from your feed;
  - tags films with moods, explains "Why this?", sums up your taste in plain words, and writes a themes and values note for parents.

  Everything works without it. Prompts carry films and an aggregated taste summary, never usernames or server details, and every call is logged for admins.
- **Your data stays yours:** one container and SQLite, no mandatory paid services; runs alongside Jellyfin on a home server or NAS. The server backs up its database every day and before each upgrade, and you can export your own data to move it to another server.
- **Installable:** add it to your phone's home screen or install it from Chrome or Edge, and it opens like an app. Installing needs HTTPS, such as from the reverse proxy in front of Jellyfin, except on iOS.
- **For tinkerers:** a read-only MCP server for debugging, protected by a key an admin creates.

Web app first; Android and iOS apps will use the same server API.

## Quick start (Docker)

```sh
git clone https://github.com/sinoop/iwanttowatch.git
cd iwanttowatch
docker compose up -d
```

This pulls the published image, built for amd64 and arm64 (such as a Raspberry Pi 4 or 5). Open `http://<your-server>:8080` and follow the setup wizard to create the admin account, then add a free [TMDb API key](https://www.themoviedb.org/settings/api) in Settings. Jellyfin, streaming services, and the AI are set up in Settings too. Data is stored in the `iwanttowatch-data` Docker volume.

The [install guide](docs/install.md) walks through each step, including the Jellyfin webhook, HTTPS for installing the app, restoring a backup, and troubleshooting.

### Updating

```sh
git pull                 # picks up changes to docker-compose.yml
docker compose pull
docker compose up -d
```

`latest` follows every change on `main` that passes the checks; to stay on a release, set `image:` in `docker-compose.yml` to a version tag such as `ghcr.io/sinoop/iwanttowatch:0.1`. The server copies its database before running any upgrade, so you can go back if something goes wrong. To build from your checkout instead of pulling, run `docker compose up -d --build`.

## Project layout

| Path | What |
| --- | --- |
| `server/` | Python API server (FastAPI, SQLAlchemy, Alembic, SQLite) |
| `web/` | Web app (React, TypeScript, Vite, Tailwind) |
| `packages/api-client/` | TypeScript API client generated from the server's OpenAPI schema, shared with future mobile apps |
| `Dockerfile`, `docker-compose.yml` | Single-container deployment |

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development setup.

## Roadmap

0. Foundations: server, web shell, setup wizard, Docker, CI
1. Catalog (TMDb) and IMDb/Letterboxd import
2. Jellyfin connection and automatic scrobbling
3. Streaming availability per region
4. Recommendation engine and discovery feed
5. Feedback loop, Watch together, child profiles, shortlists and platform filter
6. Optional integrations and polish: AI features, Netflix import, invites, debugging, the installable app, and backups are done; Trakt, Watchmode, critic scores, Google sign-in, and translations remain
7. First release, v0.1.0 ✓
8. **Mobile apps** ← *next*, then a TV app

The detailed plan, with what each phase delivered, is in [docs/plan.md](docs/plan.md).

## Licence and trademark

iWantToWatch is free software: you can redistribute it and/or modify it under the terms of the [GNU Affero General Public License v3.0 or later](LICENSE). If you run a modified version as a network service, you must offer its source code to its users.

The iWantToWatch name and logo are trademarks; see [TRADEMARK.md](TRADEMARK.md) for what is allowed.
