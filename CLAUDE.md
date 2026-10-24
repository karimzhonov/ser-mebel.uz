# ser-mebel.uz

## ⚠️ Working scope (project owner's rule — overrides anything below)

- **Work only in `backend/` and `frontend/`.** The product is now: Django REST API (`backend/api/` + `<app>/services.py` + models) → React SPA (`frontend/`).
- **Forget the Django admin.** Do not add features, fixes, actions, components, sidebars or templates for the admin (`*/admin.py`, `actions.py`, `components.py`, `forms.py` used only by admin, `core/unfold.py`, `core/sidebars.py`, `core/tabs.py`, `core/views.py` dashboard, admin templates/static). It stays mounted at `/admin/` only as a legacy fallback — don't delete it unless asked, but don't build on it or use it as the reference for new behavior.
- Every new feature = model/service in `backend/` + endpoint in `backend/api/` + UI in `frontend/`. Business rules live in `<app>/services.py` (source of truth); the API calls them.
- Don't touch `bot/` unless the owner explicitly asks. If an API/model change would affect the bot contract (`oauth.User` schema, `telegram_id`, `send_message`), stop and flag it instead of editing the bot.
- **Git: always work on the `test` branch.** Don't create feature branches; commit straight to `test` (check `git branch --show-current` first, switch to `test` if needed). Pushing `test` auto-deploys to staging (`.github/workflows/deploy.yml`), so push only when the owner asks. `master` = production — never commit or push to it without an explicit request.
- **Release flow (owner's rule):** every change goes `test` branch → staging **https://test.ser-mebel.uz** (admin: https://test.ser-mebel.uz/admin/) → owner checks it there → owner merges `test` into `master` via a GitHub PR → production https://ser-mebel.uz. Never skip staging; never deploy to production yourself. When reporting a finished change, say what to check on test.ser-mebel.uz.
- Frontend: React 18 + TypeScript + Vite + Tailwind + TanStack Query; UI text in Russian like the rest of the panel; check permissions with `useAuth().can(...)` and always enforce the same rule server-side.

Two-service project. Full findings: `docs/ARCHITECTURE_ANALYSIS.md` — read it before any cross-cutting work.

## Services

- `backend/` — Django 5.2: django-unfold admin + DRF REST API (`backend/api/`, JWT). See `backend/CLAUDE.md`.
- `frontend/` — React 18 + Vite + TypeScript + Tailwind SPA on top of that API (same features as the admin). See `frontend/README.md`. Node 22; `npm run dev` proxies `/api` to :8000.
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

Dev: `docker-compose.yml` — `back` (Django via `runserver.sh`, port 8000) + `db` (Postgres 18) + `front` (Vite, port 5173). Bot is **not** in dev compose — run it separately (`python runbot.py` for polling, from `bot/`) when working on it locally.

Prod: `docker-compose.prod.yml` — `front` (nginx) publishes `BACK_PORT` (8000) so the server nginx needs no changes; it serves the SPA + /media + /static and proxies /api, /admin, /filer (and `/?telegram_id=`) to `back`, which is no longer published. `bot` (port 7000→80), `db` (Postgres 18). CI builds 3 images (api/front/bot). Details: `docs/DEPLOY.md`. Both `back` and `bot` need their `POSTGRES_*` env vars in sync since they connect to the same database independently.

## Orchestration rules (subagent pipeline)

Pipeline: **architect → (django-dev and/or bot-dev, per scope) → tester → reviewer → fix loop (max 3) → done.**

- Per the working-scope rule above: tasks are backend (API/services/models) and/or frontend. `bot-dev` is only used when the owner explicitly asks for bot work. Frontend changes must pass `npm run build` (typecheck + build) before review.
- Task touches only Django → `django-dev` only.
- Task touches only the bot → `bot-dev` only.
- Task touches both services OR the `oauth.User` contract (schema, the `/start` flow, `send_message`/`/user/{chat_id}/message`) → both dev agents + `integration-guard` runs after coding, before `reviewer`.
- Never skip `tester`/`reviewer` for real business-logic changes. Trivial changes (typo, copy tweak, comment) may skip the pipeline — say so explicitly when you do.
- End every pipeline run with a summary: **designed / changed / tested (results) / reviewed.**

Agents live in `.claude/agents/`. Slash commands (`/feature`, `/fix`, `/review`, `/sync-check`) live in `.claude/commands/`.
