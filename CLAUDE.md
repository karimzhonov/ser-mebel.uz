# ser-mebel.uz

Two-service project. Full findings: `docs/ARCHITECTURE_ANALYSIS.md` — read it before any cross-cutting work.

## Services

- `backend/` — Django 5.2 admin-only app (django-unfold theme). No DRF, no public API. See `backend/CLAUDE.md`.
- `bot/` — aiogram 3.22 Telegram bot wrapped in FastAPI (webhook mode in prod). See `bot/CLAUDE.md`.

## How the services actually talk to each other

**Not a REST contract.** Read this before touching anything that crosses the boundary:

- **bot → backend**: the bot has its own Tortoise ORM model (`bot/db/models/oauth.py`) that mirrors Django's `oauth.User` table (`oauth_user`) by hand, connected to the **same Postgres instance**. The bot writes `telegram_id` directly into that table on `/start`, bypassing Django's ORM, validation, and signals entirely.
- **backend → bot**: real HTTP. `oauth.User.send_message()` (Django) does `requests.post` to `{TELEGRAM_BOT_SERVER}/user/{chat_id}/message`, hitting the bot's FastAPI route `bot/api/routes.py`.
- **No shared migration source of truth.** A Django migration on `oauth.User` (rename/drop a column, add NOT NULL) can silently break the bot with nothing to catch it. Any change to `oauth.User`'s schema MUST be manually mirrored in `bot/db/models/oauth.py`, and vice versa — treat this pair of files as one contract.
- There is no shared Python package between the two services. Do not try to import Django code from the bot or vice versa — the coupling is DB-level and HTTP-level only, never a Python import.

## Shared conventions

- Python 3.10 in both services (see both Dockerfiles) — don't use syntax newer than 3.10.
- Formatter/lint: `black` + `ruff` (`pyproject.toml` in each service dir, added because none existed before). Run per-service, not from repo root.
- Commit style: this repo has no enforced convention (history is mostly bare "fixes"). When asked to write a commit message, prefer a real one-line description of *why*, not "fixes" — don't imitate the existing sloppy history.
- Never edit an already-applied migration. Never touch `.env` files (not in the repo; don't try to read or create them).

## Running both services

Dev: `docker-compose.yml` — `back` (Django via `runserver.sh`, port 8000) + `db` (Postgres 18). Bot is **not** in dev compose — run it separately (`python runbot.py` for polling, from `bot/`) when working on it locally.

Prod: `docker-compose.prod.yml` — `back` (uvicorn ASGI, port 8000), `bot` (uvicorn/FastAPI, port 7000→80), `db` (Postgres 18). Both `back` and `bot` need their `POSTGRES_*` env vars in sync (`backend/.env` and `bot/.env` respectively) since they connect to the same database independently.

## Orchestration rules (subagent pipeline)

Pipeline: **architect → (django-dev and/or bot-dev, per scope) → tester → reviewer → fix loop (max 3) → done.**

- Task touches only Django → `django-dev` only.
- Task touches only the bot → `bot-dev` only.
- Task touches both services OR the `oauth.User` contract (schema, the `/start` flow, `send_message`/`/user/{chat_id}/message`) → both dev agents + `integration-guard` runs after coding, before `reviewer`.
- Never skip `tester`/`reviewer` for real business-logic changes. Trivial changes (typo, copy tweak, comment) may skip the pipeline — say so explicitly when you do.
- End every pipeline run with a summary: **designed / changed / tested (results) / reviewed.**

Agents live in `.claude/agents/`. Slash commands (`/feature`, `/fix`, `/review`, `/sync-check`) live in `.claude/commands/`.
