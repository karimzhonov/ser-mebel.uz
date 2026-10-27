# ser-mebel.uz — Architecture Analysis

Date: 2026-07-11
Scope: `backend/` (Django admin app) + `bot/` (aiogram v3 / FastAPI service) + their integration.

## 0. Corrected premise

This is **not** an API backend + bot-client pair. `backend/` is a **Django-admin-only application** (django-unfold themed admin, zero DRF, effectively one public URL). `bot/` is a **FastAPI app that embeds an aiogram v3 Dispatcher** and talks to Django's database directly through a second, hand-maintained ORM (Tortoise), not through any Django API. There is no REST contract to break — the real contract is the shared Postgres schema (specifically `oauth_user`) plus one HTTP call in each direction.

```
Telegram ⇄ aiogram v3 Dispatcher (bot/bot/__init__.py, webhook mode via FastAPI)
                │
                ├─ direct Tortoise ORM read/write ─────────────┐
                │                                              ▼
Django (admin only, no DRF) ──────────── shared Postgres ("oauth_user" + all other tables)
   oauth.User (AbstractBaseUser)                               ▲
        │ send_message() ── requests.post ──────────────────────┘ (Django → bot HTTP)
        ▼
POST {TELEGRAM_BOT_SERVER}/user/{chat_id}/message  (bot/api/routes.py)
```

## 1. Django service (`backend/`)

- **Settings**: single file `core/settings.py`, no dev/prod split, `python-dotenv` + `os.getenv`. `SECRET_KEY` silently falls back to a random value if unset (kills sessions on every restart if `.env` missing). `ALLOWED_HOSTS=["*"]`, `X_FRAME_OPTIONS='ALLOWALL'`, wide `CSRF_TRUSTED_ORIGINS` — deliberate, to let the admin run inside Telegram WebApp, but widens attack surface.
- **Apps**: `oauth`, `client`, `call_center`, `metering` (+`design`, `price`), `order` (+`assembly`, `detailing`, `painter`, `rover`), `accounting`, `discussion`, `core`. Custom user model `oauth.User` (phone-based, no username/email), ad-hoc permission flags per domain instead of Django groups.
- **No DRF**, no `services.py`/`selectors.py` anywhere. Business logic lives in `post_save` signal handlers (folder creation, cross-model price cascades, synchronous Telegram notifications) and in admin `actions.py`/`components.py` files. `order/detailing/models.py` in particular orchestrates three sibling models' pricing inline in a signal.
- **CORS** middleware installed, zero `CORS_*` config → effectively locked shut; looks like leftover/unused.
- **No Celery/background task queue.** All side effects (Telegram push, currency-rate lookup via `cbu.uz` inside `ConvertedCostManager`) run synchronously in the request/signal path with a bare `except Exception`.
- **No `db_index` anywhere in the schema**, notably missing on `Order.status` / `Metering.status`, the two fields every admin list and dashboard filters/groups by.
- **N+1s**: `OrderAdmin`, `MeteringAdmin`, `InvoiceAdmin` all show a `client` FK column with no `list_select_related`; `OrderWaitListComponent` iterates orders calling `str(row.client)` per row.
- **Security**: `oauth/views.py`'s `telegram_admin_login` logs a user in by trusting a raw `telegram_id` query param with **no HMAC/signature verification** of the Telegram payload — a real account-takeover risk if that ID leaks (URLs, logs, referrers).
- **Tests**: none. No `pytest`/`pytest-django`, no real test files anywhere — every `tests.py` is the untouched Django stub.
- **Migrations**: ~108 files across 13 apps, no branching detected by filename inspection. `order` (19) and `metering.price` (13) are most iterated.
- **Static/media**: filer-based folder hierarchy (not plain FileField), served by nginx in prod, by Django's `static()` helper in dev.
- **Dead code**: expense auto-creation from Assembly/Painter/Rover is commented out in 3 files — accounting↔production integration appears intentionally disabled but not cleaned up. Worth confirming with the team.

## 2. aiogram bot (`bot/`)

- **Version confirmed: aiogram v3.22.0**, and code idioms match v3 (`Dispatcher(storage=MemoryStorage())`, `@dp.message()` decorator, `dp.feed_update`, `dp.resolve_used_update_types()`). No v2 leftovers found.
- **Structure is minimal** — no `handlers/`, `keyboards/`, `states/`, `middlewares/` packages. Everything lives in 3 files (`bot/bot/__init__.py`, `utils.py`, `webhook.py`) plus `api/routes.py` (FastAPI) and `db/` (Tortoise). Exactly **one** aiogram handler exists (a catch-all `@dp.message()` on the global `Dispatcher`, no `Router` used at all).
- **Webhook mode in prod** (`main.py` = FastAPI app wrapping the Dispatcher, run via `uvicorn main:app --workers 4`), **polling mode available** for local dev (`runbot.py`). 4 uvicorn workers each construct their own `Bot`/`Dispatcher`/`MemoryStorage` — fine while stateless, a landmine the moment real FSM state is added.
- **No FSM states, no middlewares, no rate limiting, no structured logging** (bare `print()` only).
- **The one handler is fat and unguarded**: parses `/start <user_id>` manually (not via aiogram's `CommandStart(deep_link=True)`), does `User.get_or_none(id=user_id)` then `user.telegram_id = ...; user.save()` with **no null-check and no try/except** — a bad/stale deep-link id raises an unhandled `AttributeError` straight out of the webhook request.

## 3. Integration layer - the real contract

> **Updated 2026-10-27 (bot refactor).** The original findings below this note (shared-DB
> mirror, no contract) are history; the section describes the integration as it is now.
> Full wire contract: `docs/BOT_CONTRACT.md`.

```
Telegram ⇄ bot/ (aiogram 3 + FastAPI, Redis FSM / dedup / locks; renders every message)
              │  signed HTTP, HMAC-SHA256(BOT_TOKEN), X-Bot-Timestamp / -Actor / -Signature
              │  bot -> backend:  /api/v1/bot/...   (identity, link, finance, HR)
              │  backend -> bot:  POST /notify (events), GET /files/{file_id}, POST /user/{chat_id}/message
              ▼
backend/ (Django + DRF)  api/views/bot/*  ->  <app>/services.py (rules)  ->  Postgres
              │  accounting/events.py, hr/events.py  ->  core.bot_notify.emit (transaction.on_commit)
              ▼
         Celery core.tasks.notify_bot (retry x8, backoff, stable envelope id)  ->  bot /notify
```

- **The bot has no database.** The Tortoise mirror of `oauth.User` (`bot/db/models/oauth.py`)
  and the bot's Postgres connection are gone. `/start <payload>` from the site's "connect
  Telegram" link calls `POST /api/v1/bot/link/ {token, telegram_id}`; the backend verifies the
  token and writes `oauth_user.telegram_id` (`oauth.services.link_telegram`).
- **Link tokens are signed.** `core.telegram.link_token(pk)` = `u{pk}_{hmac10}`, HMAC-SHA256
  of the user pk keyed with `SECRET_KEY` (only the backend signs and verifies; revoking the
  bot token does not break links). Plain digits are still accepted for one release and
  logged as deprecated. `TELEGRAM_WEBAPP_LOGIN_ENABLED` stays off until that fallback is
  removed.
- **Signed both ways.** `core/bot_signing.py` (`sign` / `verify`, +-300 s window,
  `compare_digest`). `api.authentication.BotSignatureAuthentication` + `api.permissions.IsBot`
  guard `/api/v1/bot/`; a JWT alone never reaches it, and the endpoints are excluded from the
  Swagger schema. The acting Telegram id travels in the signed `X-Bot-Actor` header, so every
  role rule is enforced by the backend.
- **Events, not Telegram calls.** The backend never calls the Telegram Bot API. Business
  code emits a data-only event after the transaction commits; Celery delivers it. Jobs that
  need the delivery result (HR asks) send synchronously and stop quietly when the bot is
  down. `oauth.User.send_message()` -> `POST /user/{chat_id}/message` is unchanged (BOT_SERVER
  is `http://bot:80` in compose).
- **Still no shared package.** The coupling is HTTP + the documented JSON shapes
  (`docs/bot_contract/*.json`, loaded by both test suites) - no shared schema to drift.

## 4. Risks ranked by severity

1. **Critical — unauthenticated admin login via raw `telegram_id`** (`backend/oauth/views.py`). No signature verification means anyone who obtains a valid `telegram_id` can log into the Django admin as that user. This is the single highest-severity finding in the whole codebase.
2. **High — shared-database coupling with no contract enforcement.** Bot's Tortoise model duplicates Django's `oauth.User` schema by hand; a routine Django migration can silently break bot login/notifications with no test or CI signal.
3. **High — zero automated tests across both services.** No repro-test safety net for a codebase that already has non-trivial cross-model business logic (order/detailing cascades, pricing engine).
4. **Medium — unhandled exception in the bot's only handler.** Bad `/start` deep link → unhandled `AttributeError` on every malformed/stale payload, no try/except, no logging framework to even diagnose it in prod (bare `print()`).
5. **Medium — synchronous external HTTP calls embedded in hot paths with no timeout/retry/queue.** `ConvertedCostManager.get_rate()` hits `cbu.uz` on every queryset build for money-related admin pages; `User.send_message()` blocks a Django request/signal on the bot's availability. No Celery/task queue exists to move these off the critical path.
5b. **Medium — missing indexes on `Order.status`/`Metering.status`** plus N+1s on every admin list showing `client` (Order/Metering/Invoice admins), and a live currency-rate HTTP call embedded in `ConvertedCostManager.get_queryset()`.

## 5. Top 5 recommended improvements

1. **Verify the Telegram login payload** (HMAC hash per Telegram's WebApp `initData` spec, or a short-lived signed token minted by the bot) before calling `login()` in `oauth/views.py`. This is the only item here with real security exposure — should be fixed before anything else.
2. **Replace the bot's shadow Tortoise `User` model with a thin, explicit HTTP contract** (a Django endpoint or a tightly-scoped internal API the bot calls to look up/link a user by phone or a one-time token), or at minimum add a CI check that diffs the two schemas so a Django migration can't silently break the bot. Direct shared-DB writes bypassing Django's ORM should go away.
3. **Add `try/except` + structured logging around the bot's message handler**, and adopt a Router-based structure (`Router()` + `dp.include_router()`) plus real FSM states as soon as a second handler is added, so the "one handler, no error handling" pattern doesn't compound.
4. **Introduce a minimal services layer in Django** (`services.py` per app) and move signal-handler business logic (folder cascades, price recomputation, Telegram notifications) there; wrap multi-model writes (e.g. `order/detailing`'s three-model cascade) in `transaction.atomic()`. This is prerequisite work for adding tests, since signal-embedded logic is hard to unit test in isolation.
5. **Add `pytest`/`pytest-django` and write first tests for the highest-risk logic**: the login view (once patched), the order/detailing pricing cascade, and the bot's `/start` handler (mocked `Bot`/`Dispatcher`). Currently zero automated coverage exists on either service.

Additional lower-priority but easy wins: add `db_index=True` to `Order.status`/`Metering.status`; add `list_select_related`/`select_related` to Order/Metering/Invoice admins; cache or move the `cbu.uz` currency-rate lookup out of `ConvertedCostManager.get_queryset()`; decide and clean up the commented-out accounting↔production integration; remove or configure the unused CORS middleware; pin `requests`/`openpyxl` versions in `backend/requirements.txt`.
