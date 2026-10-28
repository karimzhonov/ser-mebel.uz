# backend/ — Django service

DRF REST API in `api/` (JWT auth) serving the React SPA in `../frontend/`. That is the product. The django-unfold admin at `/admin/` is frozen legacy — don't develop it (root CLAUDE.md, "Working scope").

## REST API (`api/`)

- One app, `api/`: `serializers/<domain>.py`, `views/<domain>.py`, routes in `api/urls.py` under `/api/v1/`. Swagger at `/api/docs/`.
- Views stay thin: every write goes through an `<app>/services.py` function (e.g. `order.services.send_order_to_detailing`). Services raise `core.exceptions.ServiceError` for business-rule refusals; `api/exceptions.py` turns it into a 400.
- Permissions mirror the admin: `api.permissions.ModelPermissions` (view_/add_/change_/delete_ per HTTP method) on CRUD; custom `@action`s need view_ on the model plus the exact admin permission via `require_perm(...)`. Row scoping (assemblers see own jobs, accounting non-superusers see own rows) is in `get_queryset`, same as the admin.
- Money is `{"amount", "currency"}` (`api.fields.MoneyField`). Order money fields are hidden without `order.view_order_price`.
- **The Django admin is frozen legacy** (see root CLAUDE.md "Working scope"). `<app>/services.py` is the source of truth for business rules; do not update admin actions/forms/components to follow service changes, and don't use the admin as the spec for new behavior.
- Telegram WebApp login: `/api/v1/auth/telegram/` verifies `initData` HMAC (`oauth.services.verify_telegram_init_data`) but is OFF by default (`TELEGRAM_WEBAPP_LOGIN_ENABLED`). Linking is authenticated (only the signed `?start=u{pk}_{hmac10}` token links; plain digits are refused). The old unauthenticated `/?telegram_id=` admin login was removed.

## Bot channel (Telegram lives in `bot/`, not here)

The backend sends nothing to Telegram and holds no bot logic. Contract: `../docs/BOT_CONTRACT.md` (+ JSON examples in `../docs/bot_contract/`).

- **Internal API** `/api/v1/bot/...` (`api/bot_urls.py`, views in `api/views/bot/{base,common,finance,hr}.py`). Auth: `api.authentication.BotSignatureAuthentication` (HMAC-SHA256 keyed with `BOT_TOKEN`, `core/bot_signing.py`, headers `X-Bot-Timestamp` / `X-Bot-Actor` / `X-Bot-Signature`, ±300 s) + `api.permissions.IsBot`. `request.auth` is the acting Telegram id. Not in `/api/docs/`. Views stay thin: role check (`BotAPIView.require_*`) -> `<app>/services.py` -> `accounting.events` / `hr.events`. `ServiceError` = 400, `ServiceConflict` = 409, `ServiceForbidden` = 403 (on the site API all three stay 400).
- **Events** (backend -> bot): `core.bot_notify.emit(event, data)` queues `core.tasks.notify_bot` via `transaction.on_commit` (8 retries, backoff, stable envelope id; the bot dedups on it) -> bot `POST /notify`. Payload builders: `accounting/events.py`, `hr/events.py`; DTOs: `accounting/dto.py`, `hr.services.employee_dto`. Data only: ids, DTOs, recipients (`to` / `admins`, `fallback` for duties) — never message text. `send_event_sync` is for jobs that need the delivery result (HR asks); it raises `BotUnavailable`. `fetch_file(file_id)` gets receipt bytes from the bot (`GET /files/{id}`).
- **Never** add a Telegram Bot API call, `accounting/telegram`-style router or message text to the backend. New notification = a new event in the contract + a builder in `events.py` + the renderer in `bot/`.
- **Link token**: `core.telegram.link_token(pk)` / `parse_link_token(token)` — `u{pk}_{hmac10}`, HMAC-SHA256 of the pk keyed with `SECRET_KEY` (not BOT_TOKEN: revoking the bot token must not break links). `MeSerializer.telegram_link` and the admin "Связать Telegram" link use `user_bot_link(pk)`. `oauth.services.link_telegram` is what `POST bot/link/` calls.
- `BOT_SERVER` (compose: `http://bot:80`) is where events and `User.send_message` go.

## Where logic lives (and where it should go)

Reality today: business logic lives in `post_save` signal handlers (folder creation, price cascades, Telegram notifications), in admin `actions.py`/`components.py` files, and — for everything the REST API does — in `<app>/services.py` functions.

- When adding non-trivial logic (more than a simple field computation), put it in a new `<app>/services.py` function, and call it from the signal/admin action/view — don't grow the signal handler itself.
- Don't add another signal handler with inline cross-model writes if you can avoid it (see `order/detailing/models.py` for what NOT to imitate — it inlines pricing logic for 3 sibling models in one signal).
- Wrap any multi-model write in `transaction.atomic()`. Existing signal cascades (`order/detailing`, `order/painter`, `order/rover`) do not do this — don't propagate the gap into new code.
- `ModelAdmin` subclasses (`core/unfold.py` base) are the closest thing to a "view" here — keep permission checks (`has_*_permission`) simple; move real business rules to `services.py`.

## Models / migrations

- Custom user model: `oauth.User` (phone-based, `AbstractBaseUser`). After the bot refactor the bot has no database and no mirror of this table (it links accounts through `POST /api/v1/bot/link/`), so changing `oauth.User`'s fields no longer needs a bot-side change — but `link_telegram` and `telegram_id` are part of that contract: flag any change to them.
- Never edit an already-applied/committed migration file. Create a new one.
- No model in this codebase uses `db_index=True` — if you add a field that's heavily filtered/searched (like `Order.status`/`Metering.status` today), add the index; don't just copy the existing lack of one.
- `ConvertedCostManager` (`core/djmoney.py`) annotates `converted_<field>` on every queryset using the USD rate from constance `USD_CURRENCY` (no external HTTP call any more — the cbu.uz lookup is commented out). It reads `?currency=` from the current request via a class attribute set by `ConvertedCostMiddleware`.

## Admin list views (legacy — don't add new admin code)

- If you ever must touch a `ModelAdmin` with FK columns in `list_display`, set `list_select_related` (existing admins for `Order`/`Metering`/`Invoice` don't — that's a known N+1, not a pattern to copy).

## Tests

- `pytest` + `pytest-django` are set up (`pyproject.toml`, `conftest.py`). API tests live in `api/tests/` (use `rest_framework.test.APIClient` + the `api`/`admin_api` fixtures from `api/tests/conftest.py`).
- Bot channel tests: `api/tests/botkit.py` — `bot_client` signs requests like the bot service, `bot_events` collects every event `emit()` queues (no Celery, no network), `members` / `site_order` fixtures; HR: `hr/tests/hrkit.py` (`clock`, `boss`, `group`). The contract fixtures live in `../docs/bot_contract/` (not inside the backend image: mount `./docs` at `/docs` to run those tests, they skip otherwise).
- For bug fixes, write the failing test first against the actual behavior, using Django's `TestCase` unless `pytest-django` has been set up in the same change.

## Security note

- The old `telegram_admin_login` (`/?telegram_id=` logged anyone in by a raw Telegram id) was removed. Never reintroduce login by an unsigned Telegram id.

## Commands

- Format/lint: `black .` / `ruff check .` from `backend/` (config in `backend/pyproject.toml`).
- Migrate: `python manage.py makemigrations` / `python manage.py migrate`.
- Dev server: via `docker-compose.yml` (`back` service, `runserver.sh`) or `python manage.py runserver` directly.
