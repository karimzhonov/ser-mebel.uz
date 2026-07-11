# bot/ — aiogram service

**aiogram 3.22.0 — v3 idioms only.** Never use v2 syntax (`register_message_handler`, `executor.start_polling`, `@dp.message_handler()`, old middleware base classes). This codebase already uses v3 correctly (`@dp.message()`, `dp.feed_update`, `MemoryStorage` from `aiogram.fsm.storage.memory`) — match it.

## Structure today

Minimal: `bot/bot/__init__.py` (Bot/Dispatcher singletons + the one handler + keyboard builder + `send_message`), `bot/bot/webhook.py`, `bot/bot/utils.py`, `bot/api/routes.py` (FastAPI), `bot/db/` (Tortoise). **No `Router()` is used anywhere** — everything is registered on the global `dp`. When adding a second handler, switch to `Router()` + `dp.include_router()` rather than piling more `@dp.message()` calls onto the global dispatcher.

## Rules

- **Handlers stay thin.** The existing `/start` handler inlines a direct Tortoise write (`User.get_or_none` → `.save()`) with no null-check and no try/except — don't copy that. New handlers: validate input, call a `services.py` function (create one under `bot/bot/` if it doesn't exist) for any DB/business logic, catch exceptions, log them (add real logging — currently only bare `print()` exists; prefer stdlib `logging` over adding a new dependency unless asked).
- **FSM**: none exists yet. If you add multi-step conversation flow, define a `StatesGroup` in a new `states.py`, use v3 `FSMContext` (`state.set_state()`, `state.get_data()`). Remember `MemoryStorage` loses state on restart and isn't shared across the 4 uvicorn workers in prod (`docker-compose.prod.yml`) — don't rely on FSM state surviving a worker restart or being visible cross-worker without swapping storage backends first.
- **Webhook vs polling**: `main.py` (FastAPI, webhook, prod) and `runbot.py` (polling, dev) both import the same `bot`/`dp` singletons from `bot/bot/__init__.py`. Changes to handler registration affect both entry points — don't special-case one without checking the other still works.

## Calling the backend

There is no REST API to call. Two channels exist:
- **Writing to `oauth.User`**: done via the bot's own Tortoise model `bot/db/models/oauth.py`, which mirrors Django's `oauth.User` table by hand. If you add a field or change a type here, it must match `backend/oauth/models.py` exactly (same table, same column names) — check with `integration-guard` before merging.
- **Receiving a push from Django**: `bot/api/routes.py`'s `POST /user/{chat_id}/message` is called by Django's `oauth.User.send_message()`. Don't change this route's request/response shape without checking the Django caller.

Don't add new direct Tortoise models for other Django tables without discussing the coupling risk — the existing `oauth_user` mirror is already flagged as a contract risk in `docs/ARCHITECTURE_ANALYSIS.md`.

## Commands

- Format/lint: `black .` / `ruff check .` from `bot/` (config in `bot/pyproject.toml`).
- Run polling locally: `python runbot.py` (from `bot/`).
- Run webhook/prod-style locally: `uvicorn main:app --reload` (from `bot/`).
