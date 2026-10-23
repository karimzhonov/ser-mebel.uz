# backend/ — Django service

DRF REST API in `api/` (JWT auth) serving the React SPA in `../frontend/`. That is the product. The django-unfold admin at `/admin/` is frozen legacy — don't develop it (root CLAUDE.md, "Working scope").

## REST API (`api/`)

- One app, `api/`: `serializers/<domain>.py`, `views/<domain>.py`, routes in `api/urls.py` under `/api/v1/`. Swagger at `/api/docs/`.
- Views stay thin: every write goes through an `<app>/services.py` function (e.g. `order.services.send_order_to_detailing`). Services raise `core.exceptions.ServiceError` for business-rule refusals; `api/exceptions.py` turns it into a 400.
- Permissions mirror the admin: `api.permissions.ModelPermissions` (view_/add_/change_/delete_ per HTTP method) on CRUD; custom `@action`s need view_ on the model plus the exact admin permission via `require_perm(...)`. Row scoping (assemblers see own jobs, accounting non-superusers see own rows) is in `get_queryset`, same as the admin.
- Money is `{"amount", "currency"}` (`api.fields.MoneyField`). Order money fields are hidden without `order.view_order_price`.
- **The Django admin is frozen legacy** (see root CLAUDE.md "Working scope"). `<app>/services.py` is the source of truth for business rules; do not update admin actions/forms/components to follow service changes, and don't use the admin as the spec for new behavior.
- Telegram WebApp login: `/api/v1/auth/telegram/` verifies `initData` HMAC (`oauth.services.verify_telegram_init_data`) but is OFF by default (`TELEGRAM_WEBAPP_LOGIN_ENABLED`): the bot's `/start <id>` links a Telegram account to any user id unchecked, so the link can't be trusted until the bot authenticates it. Never enable it before that. The old `?telegram_id=` admin login has the same root problem — see Security note.

## Where logic lives (and where it should go)

Reality today: business logic lives in `post_save` signal handlers (folder creation, price cascades, Telegram notifications), in admin `actions.py`/`components.py` files, and — for everything the REST API does — in `<app>/services.py` functions.

- When adding non-trivial logic (more than a simple field computation), put it in a new `<app>/services.py` function, and call it from the signal/admin action/view — don't grow the signal handler itself.
- Don't add another signal handler with inline cross-model writes if you can avoid it (see `order/detailing/models.py` for what NOT to imitate — it inlines pricing logic for 3 sibling models in one signal).
- Wrap any multi-model write in `transaction.atomic()`. Existing signal cascades (`order/detailing`, `order/painter`, `order/rover`) do not do this — don't propagate the gap into new code.
- `ModelAdmin` subclasses (`core/unfold.py` base) are the closest thing to a "view" here — keep permission checks (`has_*_permission`) simple; move real business rules to `services.py`.

## Models / migrations

- Custom user model: `oauth.User` (phone-based, `AbstractBaseUser`). Its schema is mirrored by hand in `bot/db/models/oauth.py` — **any change to `oauth.User`'s fields must be reflected there too.** Flag this in your output; don't silently change one side.
- Never edit an already-applied/committed migration file. Create a new one.
- No model in this codebase uses `db_index=True` — if you add a field that's heavily filtered/searched (like `Order.status`/`Metering.status` today), add the index; don't just copy the existing lack of one.
- `ConvertedCostManager` (`core/djmoney.py`) hits `cbu.uz` synchronously on `get_queryset()` for money fields — don't chain more managers/annotations onto models that use it without knowing this cost exists.

## Admin list views (legacy — don't add new admin code)

- If you ever must touch a `ModelAdmin` with FK columns in `list_display`, set `list_select_related` (existing admins for `Order`/`Metering`/`Invoice` don't — that's a known N+1, not a pattern to copy).

## Tests

- `pytest` + `pytest-django` are set up (`pyproject.toml`, `conftest.py`). API tests live in `api/tests/` (use `rest_framework.test.APIClient` + the `api`/`admin_api` fixtures from `api/tests/conftest.py`).
- For bug fixes, write the failing test first against the actual behavior, using Django's `TestCase` unless `pytest-django` has been set up in the same change.

## Security note

- `oauth/views.py`'s `telegram_admin_login` currently trusts a raw `telegram_id` query param with no signature check. If you touch this view, do not add features on top of it without flagging that it needs HMAC verification (see `docs/ARCHITECTURE_ANALYSIS.md` §4.1).

## Commands

- Format/lint: `black .` / `ruff check .` from `backend/` (config in `backend/pyproject.toml`).
- Migrate: `python manage.py makemigrations` / `python manage.py migrate`.
- Dev server: via `docker-compose.yml` (`back` service, `runserver.sh`) or `python manage.py runserver` directly.
