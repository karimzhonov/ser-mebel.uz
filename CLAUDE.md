# ser-mebel.uz

## ⚠️ Working scope (project owner's rule — overrides anything below)

- **Work only in `backend/` and `frontend/`.** The product is now: Django REST API (`backend/api/` + `<app>/services.py` + models) → React SPA (`frontend/`).
- **Forget the Django admin.** Do not add features, fixes, actions, components, sidebars or templates for the admin (`*/admin.py`, `actions.py`, `components.py`, `forms.py` used only by admin, `core/unfold.py`, `core/sidebars.py`, `core/tabs.py`, `core/views.py` dashboard, admin templates/static). It stays mounted at `/admin/` only as a legacy fallback — don't delete it unless asked, but don't build on it or use it as the reference for new behavior.
- Every new feature = model/service in `backend/` + endpoint in `backend/api/` + UI in `frontend/`. Business rules live in `<app>/services.py` (source of truth); the API calls them.
- **Layer split (owner's rule):** all Telegram bot logic (handlers, FSM, keyboards, message texts, Bot API calls) lives in `bot/`. Database models and business/API logic live in `backend/` (the backend never talks to the Bot API and never renders Telegram texts — it exposes data/rules through `backend/api/` and asks the bot to deliver via HTTP). UI lives in `frontend/`. Bot links (`t.me/...`) are built from the `TELEGRAM_BOT_USERNAME` env, never hard-coded.
- **Background & periodic work = Celery (owner's rule).** Stack: Celery worker + celery beat + Redis (`celery-worker`, `celery-beat`, `redis` in both compose files). Any deferred work (`.delay()` / `apply_async`, e.g. outgoing notifications, heavy exports) and any periodic job is a `@shared_task` in `<app>/tasks.py`. Periodic schedules live in the DB (`django_celery_beat`) and are declared in `backend/accounting/schedule.py` (`sync_periodic_tasks()`, run on migrate). Never add a sleep-loop management command, cron, threading timer or APScheduler. Tasks must be idempotent (beat restarts / redelivery) — guard sends with a once-key like `accounting.services.once`.
- Don't touch `bot/` unless the owner explicitly asks. If an API/model change would affect the bot contract (`docs/BOT_CONTRACT.md`), stop and flag it instead of editing the bot.
- **Git: always work on the `test` branch.** Don't create feature branches; commit straight to `test` (check `git branch --show-current` first, switch to `test` if needed). Pushing `test` auto-deploys to staging (`.github/workflows/deploy.yml`), so push only when the owner asks. `master` = production — never commit or push to it without an explicit request.
- **Never push (owner's rule).** The owner pushes `test` himself. "commit qil" means commit to `test` only. Do not run `git push` — not even if it seems implied; if pushing looks needed, ask the owner instead. After committing, say that the commits are ready for him to push.
- **Release flow (owner's rule):** every change goes `test` branch → staging **https://test.ser-mebel.uz** (admin: https://test.ser-mebel.uz/admin/) → owner checks it there → owner merges `test` into `master` via a GitHub PR → production https://ser-mebel.uz. Never skip staging; never deploy to production yourself. When reporting a finished change, say what to check on test.ser-mebel.uz.
- Frontend: React 18 + TypeScript + Vite + Tailwind + TanStack Query; UI text in Russian like the rest of the panel; check permissions with `useAuth().can(...)` and always enforce the same rule server-side.

Two-service project. Full findings: `docs/ARCHITECTURE_ANALYSIS.md` — read it before any cross-cutting work.

## Services

- `backend/` — Django 5.2: django-unfold admin + DRF REST API (`backend/api/`, JWT). See `backend/CLAUDE.md`.
- `frontend/` — React 18 + Vite + TypeScript + Tailwind SPA on top of that API (same features as the admin). See `frontend/README.md`. Node 22; `npm run dev` proxies `/api` to :8000.
- `bot/` — aiogram 3.22 Telegram bot wrapped in FastAPI (webhook mode in prod). See `bot/CLAUDE.md`.

## How the services actually talk to each other

**A signed HTTP contract — `docs/BOT_CONTRACT.md` (+ `docs/bot_contract/*.json` fixtures) is the source of truth.** Read it before touching anything that crosses the boundary:

- **bot → backend**: `bot/bot/backend/client.py` calls the internal API `/api/v1/bot/...` (`backend/api/bot_urls.py`, `backend/api/views/bot/`). Every request is HMAC-signed with `BOT_TOKEN` (`X-Bot-Timestamp`, `X-Bot-Actor`, `X-Bot-Signature`; `core/bot_signing.py` ↔ `bot/bot/backend/signing.py`, same test vector). The acting Telegram user comes from `X-Bot-Actor`; every role rule is enforced in the backend. The bot has **no database access** — no Tortoise, no Postgres env.
- **backend → bot**: `core.bot_notify.emit(event, data)` → (on commit) Celery `core.tasks.notify_bot` → signed `POST {BOT_SERVER}/notify`; the bot renders texts/keyboards (`bot/bot/*/notify.py`, `@on("event")`). Also signed `GET /files/{file_id}` (receipts) and the legacy unsigned `POST /user/{chat_id}/message` used by `oauth.User.send_message()`. In compose `BOT_SERVER=http://bot:80`.
- **Account linking**: `/start u<pk>_<hmac>` (built by `core/telegram.py`, `MeSerializer.telegram_link`) → bot → `POST /api/v1/bot/link/` → `oauth.services.link_telegram`. Plain-digit `/start <pk>` is still accepted for one release.
- **Changing the contract**: add/rename an endpoint field or event payload ⇒ update `docs/BOT_CONTRACT.md` + fixtures + both sides in the same change, and run `integration-guard`. Bot FSM, update dedup and per-user locks live in Redis (db 1; Celery uses db 0).
- There is no shared Python package between the two services. Do not import Django code from the bot or vice versa — the coupling is HTTP only.

## Shared conventions

- Python 3.10 in both services (see both Dockerfiles) — don't use syntax newer than 3.10.
- Formatter/lint: `black` + `ruff` (`pyproject.toml` in each service dir, added because none existed before). Run per-service, not from repo root.
- Commit style: this repo has no enforced convention (history is mostly bare "fixes"). When asked to write a commit message, prefer a real one-line description of *why*, not "fixes" — don't imitate the existing sloppy history.
- Never edit an already-applied migration. Never touch `.env` files (not in the repo; don't try to read or create them).

## Running both services

Dev: `docker-compose.yml` — `back` (Django via `runserver.sh`, port 8000) + `db` (Postgres 18) + `front` (Vite, port 5173) + `redis` + `celery-worker` + `celery-beat`. Bot is under the `bot` profile (`docker compose --profile bot up bot`) or run it separately (`python runbot.py` for polling, from `bot/`).

Prod: `docker-compose.prod.yml` — `front` (nginx) publishes `BACK_PORT` (8000) so the server nginx needs no changes; it serves the SPA + /media + /static and proxies /api, /admin, /filer (and `/?telegram_id=`) to `back`, which is no longer published. `bot` (port 7000→80), `db` (Postgres 18), `redis`, `celery-worker`, `celery-beat`. CI builds 3 images (api/front/bot). Details: `docs/DEPLOY.md`. Only `back`/celery connect to Postgres; the bot reaches data through the API.

## Orchestration rules (subagent pipeline)

Pipeline: **architect → (django-dev and/or bot-dev, per scope) → tester → reviewer → fix loop (max 3) → done.**

- Per the working-scope rule above: tasks are backend (API/services/models) and/or frontend. `bot-dev` is only used when the owner explicitly asks for bot work. Frontend changes must pass `npm run build` (typecheck + build) before review.
- Task touches only Django → `django-dev` only.
- Task touches only the bot → `bot-dev` only.
- Task touches both services OR the bot contract (`docs/BOT_CONTRACT.md`: `/api/v1/bot/*`, `/notify` events, the `/start` link flow, `send_message`/`/user/{chat_id}/message`) → both dev agents + `integration-guard` runs after coding, before `reviewer`.
- Never skip `tester`/`reviewer` for real business-logic changes. Trivial changes (typo, copy tweak, comment) may skip the pipeline — say so explicitly when you do.
- End every pipeline run with a summary: **designed / changed / tested (results) / reviewed.**

Agents live in `.claude/agents/`. Slash commands (`/feature`, `/fix`, `/review`, `/sync-check`) live in `.claude/commands/`.
