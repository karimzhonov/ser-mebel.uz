# bot/ — aiogram service

**aiogram 3.22.0 — v3 idioms only.** Never use v2 syntax (`register_message_handler`, `executor.start_polling`, `@dp.message_handler()`, old middleware base classes).

The bot is a **thin Telegram UI**. It has **no database** and no business rules: every read/write goes through the backend's signed internal API (`/api/v1/bot/...`), and the backend pushes notifications to the bot's `POST /notify`. Contract (frozen): `docs/BOT_CONTRACT.md` + `docs/bot_contract/*.json`.

## Structure

- `config.py` — env: `BOT_TOKEN`, `WEBHOOK_URL`, `BASE_SITE`, `BACKEND_URL`, `REDIS_URL` (db 1; Celery uses 0), `TELEGRAM_BOT_USERNAME`.
- `main.py` (FastAPI, webhook, prod) / `runbot.py` (polling, dev) — both use the same `bot`/`dp` from `bot/bot/__init__.py`.
- `api/routes.py` — `POST /webhook` (checks Telegram's `X-Telegram-Bot-Api-Secret-Token` = `sha256("webhook:"+BOT_TOKEN)[:48]`, set by `set_webhook`), `POST /user/{chat_id}/message` (legacy, called by `oauth.User.send_message`; do not change its shape), signed `POST /notify` (Redis dedup `dedup:evt:{id}`), signed `GET /files/{file_id}`. `api/security.py` verifies the HMAC.
- `bot/bot/__init__.py` — `Bot`, `Dispatcher(RedisStorage(DefaultKeyBuilder(with_bot_id=True, with_destiny=True)))`, middlewares, router order: `hr.group_router` -> `common.link` -> `common.start` -> `hr.private_router` -> `finance.router`.
- `bot/backend/` — `client.py` (`backend.request(method, path, actor=, json=, params=, files=, raw=)`, errors `ServiceRefusal`(400)/`Forbidden`(403)/`NotFound`/`Conflict`(409)/`BackendDown`), `signing.py` (HMAC vector in the contract doc).
- `bot/common/` — `middlewares.py` (update dedup, per-user Redis lock, actor/`whoami`), `actor.py`, `kb.py`, `fmt.py`, `rds.py`, `link.py` (site account linking), `start.py` (plain `/start`, `/moliya`, `/start davomat`).
- `bot/notify/registry.py` — `@on("event.name")` renderers + `dispatch()`; `Notifier` records `delivered` (`blocked` on Telegram 403).
- `bot/finance/` — Moliya: `router.py`, `handlers/*`, `states.py`, `texts.py`, `keyboards.py`, `charts.py` (QuickChart), `notify.py` (`finance.*` renderers). `bot/hr/` — davomat (separate owner).

## Rules

- **Handlers stay thin**: validate input, call the backend, render the answer. Business rules and role checks live in the backend; never duplicate them here. Wrap backend errors (`finance/ctx.py: run`), log with `logging`, no `print()`.
- **Texts and `callback_data` strings are stable** (old buttons in chats must keep working).
- **FSM state is in Redis** (6 h TTL, shared by the 4 uvicorn workers). HR uses `destiny="hr"` so it never clobbers a finance draft. Per-user lock + update dedup are in Redis too; a handler exception deletes the dedup key so Telegram's retry is processed.
- **Actor middleware is OUTER** (filters need `actor`); `whoami` is cached 30 s in Redis (`whoami:{tg}`), dropped after any non-GET backend call made for that person. Paths are encoded once in `BackendClient` (pass raw refs, never `quote()` at call sites). Bot default parse mode is HTML; the legacy `send_message` sends plain text.
- **Notifications**: a new backend event needs a renderer registered with `@on` in `bot/finance/notify.py` or `bot/hr/notify.py`; unknown events answer 400 (never retried).
- `/start u<pk>_<hmac10>` (plain digits are still forwarded but the backend refuses them) goes to `POST link/`; the backend verifies the signed token. The bot never writes `oauth_user`.
- Adding an endpoint/event means changing `docs/BOT_CONTRACT.md` and the backend together; run `integration-guard`.

## Commands

- Format/lint: `black .` / `ruff check .` from `bot/` (config in `pyproject.toml`).
- Tests: `.venv/Scripts/python -m pytest -q` (fakeredis + mocked `backend.request`; needs `requirements-dev.txt`).
- Polling locally: `python runbot.py` (needs Redis and the backend reachable). Webhook-style: `uvicorn main:app --reload`.
