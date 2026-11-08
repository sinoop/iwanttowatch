# Changelog

## v0.1.0 — 2026-11-08

The first release: a self-hosted web app that learns your film taste and suggests films you haven't seen and can watch now, on your Jellyfin server or your streaming services. See the [install guide](docs/install.md) to set it up.

### Your taste

- Import ratings from IMDb (`ratings.csv`), Letterboxd (export ZIP), and Netflix viewing history, with a review queue for titles that don't match on their own.
- Rate films as Didn't like, Liked, or Loved, with up to three tags and a short note.
- A Criticker-style match percentage from your own ratings: neighbour and ridge models over genres, people, keywords, languages, and decades, calibrated per user and checked against held-out ratings. IMDb's public ratings can optionally judge quality.
- Regional cinema treated equally: multilingual titles and per-language quality norms, and deeper searches in the languages you watch most.

### Discover

- A feed of films you haven't seen, best match first, with streaming badges, mood and genre tags, and filters by service, language, and genre.
- Only films on the services you pay for or on your Jellyfin server, by default; free and ad-supported services and everything else are a chip away.
- Thumbs up or down, seen it, not now, and not interested re-rank the feed within seconds; shortlists keep films to decide on later.

### Jellyfin

- Libraries, watched films, and favourites sync every 30 minutes, or within a second through the Webhook plugin, so nothing is logged by hand.
- Household members can sign in with their Jellyfin accounts.

### Household

- Invite links, parent-managed child profiles with certificate limits per country and a parent PIN, and themes notes for parents.
- Watch together: picks scored for everyone in the room, taste links and cards for friends on other servers, and guest voting from a phone.

### Optional AI (Gemini or a local Ollama model)

- Predicts ratings for the top of the feed and suggests films of its own, tags moods, explains "Why this?", sums up your taste in plain words, and answers requests such as "a light Malayalam comedy under 2 hours".
- Prompts carry films and aggregated taste only; every call is logged for admins. Everything works without it.

### Running it

- One container and SQLite, published for amd64 and arm64 at `ghcr.io/sinoop/iwanttowatch`.
- Daily database backups and one before each upgrade, keeping the newest 7; per-user data export and import.
- Installable as an app from the browser.
- A read-only MCP server for debugging, behind an admin-created key.

### Not yet

Trakt, Watchmode, critic scores, Google sign-in, translations, and the Android and iOS apps.
