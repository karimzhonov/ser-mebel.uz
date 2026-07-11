# backend/ — Django service

Admin-only app (django-unfold). **No DRF, no REST API, no `urls.py` per app** — the only `urls.py` is `core/urls.py`. Don't add DRF unless explicitly asked; there's no existing pattern for it.

## Where logic lives (and where it should go)

Reality today: business logic lives in `post_save` signal handlers (folder creation, price cascades, Telegram notifications) and in admin `actions.py`/`components.py` files. There is **no `services.py`/`selectors.py` layer anywhere yet**.

- When adding non-trivial logic (more than a simple field computation), put it in a new `<app>/services.py` function, and call it from the signal/admin action/view — don't grow the signal handler itself.
- Don't add another signal handler with inline cross-model writes if you can avoid it (see `order/detailing/models.py` for what NOT to imitate — it inlines pricing logic for 3 sibling models in one signal).
- Wrap any multi-model write in `transaction.atomic()`. Existing signal cascades (`order/detailing`, `order/painter`, `order/rover`) do not do this — don't propagate the gap into new code.
- `ModelAdmin` subclasses (`core/unfold.py` base) are the closest thing to a "view" here — keep permission checks (`has_*_permission`) simple; move real business rules to `services.py`.

## Models / migrations

- Custom user model: `oauth.User` (phone-based, `AbstractBaseUser`). Its schema is mirrored by hand in `bot/db/models/oauth.py` — **any change to `oauth.User`'s fields must be reflected there too.** Flag this in your output; don't silently change one side.
- Never edit an already-applied/committed migration file. Create a new one.
- No model in this codebase uses `db_index=True` — if you add a field that's heavily filtered/searched (like `Order.status`/`Metering.status` today), add the index; don't just copy the existing lack of one.
- `ConvertedCostManager` (`core/djmoney.py`) hits `cbu.uz` synchronously on `get_queryset()` for money fields — don't chain more managers/annotations onto models that use it without knowing this cost exists.

## Admin list views

- When adding a model to a `ModelAdmin` with FK columns in `list_display`, set `list_select_related` (existing admins for `Order`/`Metering`/`Invoice` don't — that's a known N+1, not a pattern to copy).

## Tests

- No test infrastructure exists (`pytest`/`pytest-django` not installed, `tests.py` files are stubs). If you add `pytest-django`, add it to `requirements.txt` and create a `pytest.ini`/`pyproject.toml` `[tool.pytest.ini_options]` block — don't assume one exists.
- For bug fixes, write the failing test first against the actual behavior, using Django's `TestCase` unless `pytest-django` has been set up in the same change.

## Security note

- `oauth/views.py`'s `telegram_admin_login` currently trusts a raw `telegram_id` query param with no signature check. If you touch this view, do not add features on top of it without flagging that it needs HMAC verification (see `docs/ARCHITECTURE_ANALYSIS.md` §4.1).

## Commands

- Format/lint: `black .` / `ruff check .` from `backend/` (config in `backend/pyproject.toml`).
- Migrate: `python manage.py makemigrations` / `python manage.py migrate`.
- Dev server: via `docker-compose.yml` (`back` service, `runserver.sh`) or `python manage.py runserver` directly.
