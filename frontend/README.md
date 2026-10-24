# ser-mebel.uz — frontend

React SPA for the ser-mebel.uz CRM. It does what the Django admin (`/admin/`) does —
call-centre, замеры, дизайн, расчёт цены, заказы, производство, бухгалтерия — through
the REST API in `backend/api/`. The Django admin keeps working alongside it.

Stack: React 18 · TypeScript · Vite 5 · Tailwind CSS 3 · TanStack Query 5 · React Router 6 · Recharts.

## Run locally

```bash
# 1. backend (from backend/) — needs the new API packages
pip install -r requirements.txt
python manage.py runserver            # :8000

# 2. frontend (from frontend/)
npm install
npm run dev                           # http://localhost:5173
```

Vite proxies `/api`, `/media`, `/admin`, `/static` to `http://localhost:8000`, so no CORS
setup is needed in dev. Point it elsewhere with `VITE_BACKEND_URL=http://host:port npm run dev`.

Log in with a staff user's phone + password (same account as `/admin/`).

## Login

- **Phone + password** → JWT (`/api/v1/auth/login/`), refreshed automatically.
- **Inside Telegram** (opened from the bot as a WebApp) → automatic login: the SPA sends
  `Telegram.WebApp.initData` to `/api/v1/auth/telegram/`, which verifies its HMAC signature
  with the bot token before trusting the Telegram user id. The user must have linked
  Telegram first (sidebar → ✈ icon, same deep link as the admin's "Связать Telegram").

## Permissions

The UI shows only what the user's Django permissions allow (same codenames the admin
uses: `order.view_order`, `order.view_order_price`, `assembly.manager`, …). The API
enforces the same rules server-side — hiding a button is never the only check.

## Production

`Dockerfile` builds the SPA and serves it with nginx; `nginx.conf` proxies `/api`,
`/admin`, `/filer`, `/media`, `/static` to the `back` container. Serving SPA + API from
one domain means no CORS. If the SPA lives on another origin, set
`CORS_ALLOWED_ORIGINS` (comma-separated) in the backend env, and build with
`VITE_API_URL=https://api.example.com`.

API docs (Swagger): `/api/docs/`.

## Layout

```
src/
  api/          axios client (JWT + refresh), types, react-query hooks
  auth/         AuthContext (login, Telegram auto-login, permission helpers)
  components/   ui/ (design system), layout/ (sidebar, mobile tab bar), domain widgets
  pages/        one file per section
```
