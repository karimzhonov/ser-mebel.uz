# Bot <-> backend contract (frozen, Phase 0)

The Telegram bot (`bot/`) holds no business rules and no database connection. The backend
(`backend/`) owns data and rules (`<app>/services.py`) and exposes a signed internal API
under `/api/v1/bot/...`. The backend tells the bot what to send through Celery
(`core.tasks.notify_bot`) which calls the bot's `POST /notify`.

Reference implementation: `backend/core/bot_signing.py` (signing), `backend/core/bot_notify.py`
(`emit`, `send_event_sync`, `fetch_file`), `backend/api/views/bot/*` (endpoints),
`backend/accounting/events.py`, `backend/hr/events.py`, `backend/call_center/events.py`, `backend/metering/events.py` and `backend/order/rover/events.py`, `backend/order/painter/events.py`, `backend/order/assembly/events.py` (event payload builders).

Example JSON fixtures: `docs/bot_contract/`.
- `dto.<name>.<n>.json` - one example of each DTO (section 1.2).
- `event.<event.name>.json` - a full `/notify` envelope per event (section 1.5).
- `misc.*.json` - request/response examples (whoami, link, notify response, HR group message ...).

Both test suites (backend and bot) load these files.

## 0. Signing test vector (both directions)

Computed by `core.bot_signing.sign`:

```
token   = "123456:TEST-BOT-TOKEN"
ts      = 1700000000
method  = "POST"
path    = "/api/v1/bot/whoami/"
actor   = "42"
nonce   = "0123456789abcdef0123456789abcdef"
body    = b'{"a":1}'
msg     = b"1700000000\nPOST\n/api/v1/bot/whoami/\n42\n0123456789abcdef0123456789abcdef\n" + b'{"a":1}'
hex     = 83d92a6128667c919f544b898f4894caae20cb08ed1c7af9452b8202ace3dd3d
```

`hex = HMAC_SHA256(key=token.encode(), msg).hexdigest()`. Both test suites assert this value.
`path` is the path with the query string exactly as sent (`/api/v1/bot/finance/orders/?buckets=a,b`);
the same string is used by signer and verifier. For `GET` the body is empty; for multipart
the body is the raw multipart bytes as sent.

Backend -> bot calls (`POST /notify`, `GET /files/{file_id}`) are signed the same way, actor empty.
Bot -> backend calls carry `X-Bot-Actor` = the acting user's Telegram id (empty for calls without
an actor, e.g. `link/`).

## 0.1 Link token (owner decision 1)

`core.telegram.link_token(pk)` returns `"u{pk}_{hmac10}"`, where
`hmac10 = hmac.new(settings.SECRET_KEY.encode(), f"tg-link:{pk}".encode(), sha256).hexdigest()[:10]`.
Deep link: `https://t.me/<bot>?start=u5_a1b2c3d4e5`. The bot only forwards the payload
(`u\d+_[0-9a-f]{10}`; plain digits are forwarded but refused with 404) to `POST link/`; only the backend
signs and verifies. SECRET_KEY was chosen (not BOT_TOKEN) so that revoking the bot token does not
invalidate every link; links are rebuilt on each page load.

# 1. Contract

### 1.1 Signing (both directions)

Headers:
- `X-Bot-Timestamp`: unix seconds.
- `X-Bot-Actor`: acting user's Telegram id, or empty.
- `X-Bot-Nonce`: uuid4 hex (32 lowercase hex chars), fresh for every request, in BOTH directions. The signed message is `f"{ts}
{METHOD}
{path_with_query}
{actor}
{nonce}
".encode() + raw_body` (this supersedes the message in the next bullet).
- `X-Bot-Signature`: hex `HMAC_SHA256(key=BOT_TOKEN, msg)`, `msg = f"{ts}\n{METHOD}\n{path_with_query}\n{actor}\n".encode() + raw_body` (empty body for GET; raw multipart bytes for multipart).

Rules:
- Replay protection: for POST/PUT/PATCH/DELETE the backend claims the nonce (Redis SET NX, TTL 600 s) and answers 403 to a repeated or missing/malformed nonce. GET/HEAD are not tracked and may repeat freely. If the replay cache is unreachable, unsafe requests are refused (fail closed).
- Reject if `|now - ts| > 300` s or `compare_digest` fails: `403`.
- One fixed test vector (`ts=1700000000`, `POST`, `/api/v1/bot/whoami/`, actor `42`, body `{"a":1}`, expected hex); both test suites assert it.

Backend errors:
- `400 {"detail": str}` for `ServiceError` (existing `api/exceptions.py`); bot shows `❗ {detail}`.
- `403 {"detail"}` role refusal; `404 {"detail"}`; `409 {"detail"}` for "already done" (winner, holiday decision, answered request).

### 1.2 DTOs (JSON)

Decimals are strings like `"250000.00"`; dates ISO.

- **Member** `{id, telegram_id, name, username, role, is_admin, is_active_member, is_task_only, has_wallet, is_site_entry, is_feedback, is_bonus_receiver, is_deadline_receiver, site_user: str|null}` — `has_wallet` / `is_task_only` are the effective flags (the member's «Hamyon» setting auto / on / off; auto = site-entry / feedback non-admins have none). An admin can have `has_wallet=false` with `is_task_only=false` (books into others' wallets, has no own one). The bot must not infer either from the duties.
- **Category** `{code, name, emoji, kind, admin_only, no_order, archive, excluded}`
- **Operation** `{number, date, time, kind, amount, currency, orig_amount, rate, category: Category, member: {telegram_id, name}, author_tg, order_ref, comment, worker, pay_type, receipt_file_id, is_deleted, handover}`
- **OrderBrief** `{ref, client, bucket, ready_date}`
- **OrderCard** `{ref, client, phone, bucket, status_label, ready_date, end_date, ready_days_left, manual: {is_closed, price}|null, stats: {spent, collected, warehouse, cats: [{code, name, emoji, sum}], last_ops: [Operation]}}`; adds `total, currency, price_uzs, paid, rest` **only for finance admins** (server-side; replaces `full = ctx.admin`, `router.py:1309`). **Additive:** `stats.warehouse` = so'm of furnitura given from the warehouse (ombor chiqim lines for this ID, cancelled ones excluded; `"0.00"` when none); `stats.spent` now INCLUDES it; `cats` may hold a pseudo category `{code: "_ombor", name: "Furnitura (ombor)", emoji: "📦", sum}` (not a FinanceCategory row - never offered for booking). Bonus, wallets and the month report are not affected.
- **Bonus** `{order_ref, client, description, total, currency, ready_date, status, rest, days, percent, bonus, note, got_text}`
- **MoneyState** `{paid, rest, src}`
- **MoneyRequest** `{number, member: Member, amount, currency, orig_amount, reason, status, answer, created_at, admin_messages: [[chat_id, message_id]], member_balance}`
- **Advance** `{id, order_ref, order_id, client, phone, price_text, amount, currency, sum_text, by_name, status: pending|accepted|rejected, status_label, got_text, created_at}` — the advance a manager entered when creating an order, waiting for the boss («Avans tasdiqlash»)
- **Worker** `{id, name, group, position, is_boss}` (`is_boss` = the boss's own salary row: its salary takes the extra `pay_type` «Uy uchun») · **Car** `{id, name}`
- **SiteEntryTask** `{code, order_ref, client, sum_text, rest_text, taken_by, date, is_done}`
- **Feedback** `{order_ref, client, phone, status, ready_date, asked_date}` · **Warranty** `{order_ref, client, given}`
- **Employee** `{telegram_id, number, name, username, is_active, can_dm, group: {chat_id, title}|null, work_start, work_end, hours_label, ontime_until, off_days, off_days_effective, off_label}`
- **WorkGroup** `{chat_id, title, is_active}`
- **UserRef** `{id, name}` (a panel user: `oauth.User` pk and name, or the phone when unnamed)
- **LeadBrief** `{id, client: {fio, phone}, source: str\|null, source_label: str\|null, solution: int\|null, solution_label: str\|null, assigned: UserRef\|null, last_note, has_point: bool, map_url: str\|null}` (`last_note` = the lead's latest note, at most 300 chars; `has_point` = the lead has a map point, `map_url` = Yandex Maps link of the point / address, null when the lead has neither; `source` is one of `telegram, instagram, phone, showroom, recommendation, other`)
- **LocationTarget** `{kind: "invoice"\|"metering", id, client: {fio, phone}, status: int\|str\|null, status_label: str\|null, when: datetime\|null, address, has_point, mine}` - a lead (`status` = answer code, `when` = created) or a metering (`status` = metering status key, `when` = its date) the bot may attach a received Telegram location to; `mine` = the lead (or the metering's lead) is assigned to the actor. **Coordinates are strings with 6 decimals (`"41.311081"`) everywhere in responses and events; requests may send numbers or strings.**
- **MeteringBrief** `{id, rev, client: {fio, phone}, status, status_label, date_time: datetime\|null, address, map_url: str\|null, has_point: bool, desc, measurer: UserRef\|null, operator: UserRef\|null, next_step: ""\|"design_price"\|"price", cancel_reason, url}` (example: `dto.metering_brief.1.json`). `status` is the metering status key (`created`, `other_day` = waiting for the measurer; `metering_done` = measured, «Ma'lumot kutilmoqda»; `done` = files + note + next step done; `dont_need` = cancelled; `sold_out`); `rev` is bumped on every status / time / measurer change (the bot keeps the last applied `rev` per metering and ignores older events); `operator` = the lead's owner (or whoever created the metering); `url` = `{ADMIN_BASE_URL}/meterings/{id}`.
- **OfferTask** `{kind: "design"|"price", id, rev, metering_id, round, stage: "work"|"review"|"approved"|"declined"|"cancelled", stage_label, client: {fio, phone}, address, map_url: str|null, due_at: datetime|null, done_at: datetime|null, assignee: UserRef|null, manager: UserRef|null, measurer: UserRef|null, note, last_comment: str|null, next_step, url, present_url}` (example: `dto.offer_task.1.json`). A Design or a Price (stage 2). `rev` is bumped on every change the bot may have shown (the bot keeps the last applied `rev` per (kind, id) and ignores older events); `round` starts at 1 and grows each time the client asked for changes / a recalculation; `due_at` is the deadline (`null` = none yet: an old row); `note` = the measurer's result note; `last_comment` = the newest comment the manager recorded; `url` = `{ADMIN_BASE_URL}/designs/{id}` or `/prices/{id}`; `present_url` = `{ADMIN_BASE_URL}/presentations?open={d|p}{id}`.
- **CrmTask** `{id, text, due_at, is_done, assigned: UserRef}` (`due_at`: naive local `YYYY-MM-DDTHH:MM:SS`)
- **WhPhoto** `{id, position, is_cover, width, height, tg_file_id}` (example: `dto.wh_photo.1.json`). `position` 0 = the cover; `tg_file_id` is a **cache** of Telegram's file_id of the main picture (`""` until the bot sent it once) - never the source of truth, the bot falls back to `GET warehouse/photos/{id}/file/` when it is empty or Telegram refuses it.
- **WhProduct** `{id, name, code, category, unit, unit_label, quantity, min_quantity, avg_cost, value, low, is_active, photos_count, cover: WhPhoto|null, url}` (example: `dto.wh_product.1.json`). Quantities are 3-place strings, money (so'm) 2-place strings; `value` = quantity x avg_cost; `low` = `min_quantity > 0` and `quantity <= min_quantity`; `url` = `{ADMIN_BASE_URL}/warehouse?search=<url-encoded code or name>`. Detail and write responses also carry `photos: [WhPhoto]` (ordered by `position`).
- **WhMovement** `{id, number, kind: "in"|"out", kind_label, quantity, unit_label, currency: "UZS"|"USD", unit_price, orig_price: str|null, rate: str|null, total, date, counterparty, allocations: [{ref, client, quantity, total}], comment, balance_after, is_cancelled, by_name, created_at}` (example: `dto.wh_movement.1.json`). `unit_price` / `total` are always so'm; `orig_price` ($ per unit) and `rate` (4 places) only for `currency == "USD"`. `allocations` (chiqim only; `[]` otherwise): the client / order IDs the act went to - `ref` is the canonical Moliya ref («406», «SM-003»), `client` a snapshot of the name, `quantity` 3-place and `total` 2-place strings (quantity x unit_price, so'm); the lines sum to the movement's `quantity` and `total`.
- **WhOrderRef** `{ref, client, bucket, status_label}` (example: `dto.wh_order_ref.1.json`) - an order / client ID a chiqim can be given to; `bucket` is `yangi|jarayonda|kutish|yakun|tugadi`.
- **RoverTask** `{id, order: {id, number}, client: {fio, phone} ("" when the order has no client), square: float, amount: str (2 places), currency, state: "new"|"checking"|"done", state_label, submitted_at: datetime|null, submitted_by: UserRef|null, checked_at: datetime|null, checked_by: UserRef|null, address: str ("" when empty), map_url: str|null, due_date: "YYYY-MM-DD"|null, due_auto: bool, due_set_by: UserRef|null, overdue: bool, days_late: int, note: str, rev: int, url, design_folder_url: str|null}` (example: `dto.rover_task.1.json`). `design_folder_url` = panel link `{ADMIN_BASE_URL}/files/{id}` to the order's «Дизайн» folder (under the metering folder), else the order folder, null when neither exists; the worker's task card shows only the client ID (= order number), this folder, the area and the deadline. A rover (milling) job: `new` = in work, `checking` = the worker handed it in with the actual `amount` (waits for a checker), `done` = a checker confirmed. `url` = `{ADMIN_BASE_URL}/production/rover?open={id}`. `due_date` = the deadline the «Ishlab chiqarish rahbari» set (or `ROVER_AUTO_DUE_DAYS` after creation when nobody did within a day: `due_auto: true`, `due_set_by: null`); `overdue` = state `new` and today > `due_date`, `days_late` = days past it (0 when not overdue); `note` = what the worker wrote on «Bajardim» ("" before); `map_url` = Yandex map link of the order's address (`core.geo.obj_map_url`); `rev` is monotonic per rover (bumped on every write).
- **PainterTask** `{id, order: {id, number}, client: {fio, phone} ("" when the order has no client), address: str ("" when empty), map_url: str|null, square: float, type: {id, name}|null, painter: UserRef|null (the type's user - the molyar), state: "new"|"done", state_label, started_at: datetime|null, done_at: datetime|null, done_by: UserRef|null, due_date: "YYYY-MM-DD"|null, due_auto: bool, due_set_by: UserRef|null, overdue: bool, days_late: int, note: str, rev: int, url}` (example: `dto.painter_task.1.json`). A painter (molyar) job; **no money**. `started_at` = the moment the job became active (type with a molyar picked AND the rover finished), set once. `url` = `{ADMIN_BASE_URL}/production/painter?open={id}`. `due_date` = the deadline the «Ishlab chiqarish rahbari» set (or `PAINTER_AUTO_DUE_DAYS` after `started_at` when nobody did within a day: `due_auto: true`, `due_set_by: null`); `overdue` = state `new` and today > `due_date`; `note` = the izoh the molyar wrote on «Bajardim» ("" before); `rev` is monotonic per painter job (bumped on every write: assignment, deadline, done).
- **AssemblyTask** `{id, order: {id, number}, client: {fio, phone} ("" when the order has no client), address: str ("" when empty), map_url: str|null, square: float, assembler: UserRef|null (the picked team - the assembler), state: "new"|"assembled"|"checking"|"done", state_label, started_at: datetime|null, finished_at: datetime|null, finished_by: UserRef|null, confirmed_at: datetime|null, confirmed_by: UserRef|null, due_date: "YYYY-MM-DD"|null, due_auto: bool, due_set_by: UserRef|null, overdue: bool, days_late: int, note: str, rev: int, url}` (example: `dto.assembly_task.1.json`). A Yig'ish/O'rnatish job; **no money**. `state`: `new` = in work, `assembled` = «Yig'ildi» pressed on the site (installing left), `checking` = «O'rnatildi» pressed by the assembler (`finished_at`/`finished_by`/`note` set), waiting for the head's «Tayyor» (state_label «Tekshiruvda»), `done` = the head confirmed (`confirmed_at`/`confirmed_by` set, the order is «Готов»; state_label «Tayyor»). `started_at` = the moment the job became active (assembler picked AND the order is in «Сборка»), set once. `url` = `{ADMIN_BASE_URL}/production/assembly?open={id}`. `due_date` = the deadline the «Ishlab chiqarish rahbari» set (or `ASSEMBLY_AUTO_DUE_DAYS` after `started_at` when nobody did within a day: `due_auto: true`, `due_set_by: null`); `overdue` = not `done` and today > `due_date`; `note` = the izoh the assembler wrote on «O'rnatildi» ("" before); `rev` is monotonic per job (bumped on every write).

### 1.3 Backend endpoints (`/api/v1/bot/`), all signed

Actor comes from `X-Bot-Actor`. Every role rule is enforced server-side.

**Common**

| Method | Path | Request | Response | Notes |
|---|---|---|---|---|
| POST | `whoami/` | `{user: {id, username, first_name, last_name}}` | `{finance_member: Member\|null, hr: {employee: Employee\|null, is_admin: bool}, crm: {linked: bool, can_add_lead: bool, can_set_location: bool}, warehouse: {is_keeper: bool}}` | `crm.linked` = the Telegram id belongs to an active staff profile on the site (the bot tells an unlinked person why a location was not taken); `crm.can_add_lead` = linked user has both `call_center.add_invoice` and `view_invoice`; `crm.can_set_location` = linked user has (`view_invoice` + `change_invoice`) or (`view_metering` + `change_metering`) (additive). Additive: `warehouse: {is_keeper: bool}` = the linked panel user is THE warehouse keeper (`WarehouseConfig.keeper`); the bot shows the «📦 Ombor» menu only then. Side effect: new `accounting.services.touch_member_username(tg, username)` (replaces `_sync_profile`, `router.py:357`) |
| POST | `link/` | `{token, telegram_id}` | `{linked, user}` / 404 | `oauth.services.link_telegram` (verifies signed token; Owner decisions #1) |

**CRM (call-centre leads)** - the actor is the panel user whose `oauth.User.telegram_id` is the `X-Bot-Actor` (active staff only). No linked user: 403 `{detail: "Telegram saytdagi profilingizga ulanmagan"}`; missing permission: 403. `ServiceError` = 400 `{detail}` (a CRM 400 may also carry `field`: `name|phone|source|remind|location|target|outcome|next_task`, additive).

| Method | Path | Request | Response | Rule |
|---|---|---|---|---|
| GET | `crm/clients/?phone=` | - | `{exists, fio\|null, invoices_count, open_invoice: LeadBrief\|null}`; 400 `{detail, field: "phone"}` for a bad number | `call_center.view_invoice`; `call_center.services.lookup_client` (open = not closed by an answer) |
| POST | `crm/due/parse/` | `{text}` (`HH:MM`, `dd.mm`, `dd.mm HH:MM`, `dd.mm.yyyy HH:MM`) | `{due_at}`; 400 `{detail, field: "remind"}` when unreadable or in the past | `call_center.add_invoice` **or** `call_center.view_invoice` (the task-done flow asks for a next-call time with view only); `services.parse_due` (a date without a time = 10:00) |
| GET | `crm/locations/candidates/?phone=` | - | `{items: [LocationTarget] (max 8), can_new_lead: bool}`; 400 `{detail, field: "phone"}` for a bad number; 403 not linked / neither permission pair | without `phone`: the actor's own leads in the answer «Mijozdan lokatsiya olish» (max 5, newest first; needs `view_invoice`+`change_invoice`), then open meterings (`created`/`other_day`, those without a point first, then by date; needs `view_metering`+`change_metering`). With `phone`: that client's open leads and editable meterings. `can_new_lead` = `add_invoice` + `view_invoice` (`services.location_candidates`) |
| POST | `crm/locations/` | `{target: {kind: "invoice"\|"metering", id}, lat, lon, address?, live?}` | `{target: LocationTarget, changed: bool, filled: [{kind, id}], map_url, url}`; `url` = the lead page / `{ADMIN_BASE_URL}/meterings/{id}`; 400 `{detail, field: "location"}` bad/out-of-range coordinates, 400 `field: "target"` malformed target, 400 archived metering; 403 missing permission for that kind; 404 | `services.set_invoice_location(via="bot")` / `metering.services.set_metering_location`; a blank-only fill: the venue `address` never overwrites a typed one; the same point again = `changed: false` (no history line); the metering and order below the target inherit the point where they have none (`filled`); `live` is informational |
| POST | `crm/leads/` | `{name, phone, source, note, remind: {preset: "today"\|"tomorrow"\|"none"} \| {at: "YYYY-MM-DDTHH:MM"}, location?: {lat, lon, address?}}` (`location` optional, additive: stored on the lead; invalid = 400 `field: "location"`; the duplicate branch ignores it) | 201 `{invoice: LeadBrief, task: CrmTask\|null, client_existed, url}`; **200 with the same body plus `"duplicate": true`** when the same linked user already created a lead for this client in the last 10 minutes (a retried POST - nothing is created; additive); 400 `{detail, field?}` (an unparsable phone is a 400 with `field: "phone"`; a non-object body is a 400) | `call_center.add_invoice`; `services.create_invoice(author=assigned=the linked user)`; an existing client keeps its name; `remind` missing = none; the task text is the default «Mijozga qo'ng'iroq qilish» |
| GET | `crm/tasks/{id}/` | - | `{task: CrmTask, invoice: LeadBrief, outcomes: [str], next_required: ["re_phone"], url}` (example: `misc.crm_task_detail_response.json`); 409 already done; 403 not the actor's task; 404 | `call_center.view_invoice` + `services.can_manage_task`; `outcomes` = `services.task_outcomes(invoice, user)` (see "Task outcomes" below) |
| POST | `crm/tasks/{id}/done/` | `{note?, outcome?: str\|null, next_task?: {preset: "1h"\|"today"\|"tomorrow"} \| {due_at: "YYYY-MM-DDTHH:MM[:SS]", text?} \|null}` (example: `misc.crm_task_done_request.json`) | `{task: CrmTask, by_name, invoice: LeadBrief (after the move), next_task: CrmTask\|null, closed_tasks: int}` (example: `misc.crm_task_done_response.json`); 400 `{detail, field: "outcome"\|"next_task"}`; 409 already done; 403 not the actor's task; 404 | `call_center.view_invoice` + `services.can_manage_task` (assignee / creator / `call_center.manage_invoice` / superuser); `services.complete_task`. Additive: `outcome`/`next_task` request fields and `invoice`/`next_task`/`closed_tasks` response fields; the rule loosened/tightened: `outcome` is now **required** when the lead is active (see below) |
| POST | `crm/tasks/{id}/snooze/` | `{preset: "1h"\|"tomorrow"}` | `{task: CrmTask}`; 409 already done; 403; 404 | same rule; `services.snooze_task` (`1h` = now + 1 hour, `tomorrow` = 10:00 tomorrow) |
| POST | `meterings/{id}/measured/` | `{}` | `{metering: MeteringBrief, url}`; 403 not the actor's metering (`ServiceForbidden`: the measurer, a `metering.manage_metering` holder or a superuser; an unassigned metering: any `oauth.user_metering` holder); 409 already marked / closed; 404 | `metering.services.mark_metering_measured`: status `metering_done`, `rev + 1`; emits `metering.changed` (`how: "measured"`) **also for this bot-initiated action** (the bot re-renders other stale cards by it) |
| POST | `meterings/{id}/reschedule/` | `{preset: "1h"\|"tomorrow"\|"2d"}` **or** `{text}` (`HH:MM`, `dd.mm`, `dd.mm HH:MM`, `dd.mm.yyyy HH:MM`; a date keeps the current clock time of the metering). Example: `misc.metering_reschedule_request.json` | `{metering: MeteringBrief}`; 400 `{detail, field: "time"}` (nothing / both given, unreadable, in the past); 403 / 409 as above; 404 missing or not in the actor's scope; no SMS to the client | `metering.services.reschedule_metering`: `1h` = now + 1 h rounded **up** to :00/:30; `tomorrow` / `2d` = +1 / +2 days at the metering's current clock time. Status becomes `other_day`, `rev + 1`; emits `metering.changed` (`rescheduled`, `watchers` = the operator when someone else moved it) |
| POST | `meterings/{id}/cancel/` | `{reason}` (>= 3 chars). Example: `misc.metering_cancel_request.json` | `{metering: MeteringBrief, lead_returned: bool}` (example: `misc.metering_cancel_response.json`); 400 `{detail, field: "reason"}`; 403 / 409 (already cancelled, or closed); 404 missing or not in the actor's scope | `metering.services.cancel_metering`: status `dont_need`, `rev + 1`; the lead returns to its operator (answer «Qayta telefon qilish» + a call task due now, so `crm.task_due` follows; the task goes to the lead's owner / creator / the operator who booked the zamer / a call-centre head — **never to the measurer**; with nobody eligible no task is made); `lead_returned: false` when the metering has no lead or the lead is already sold. Emits `metering.changed` (`cancelled`) |
| POST | `offers/{kind}/{id}/due/` (`kind` = `design`\|`price`, else 404) | `{preset: "1d"\|"2d"\|"3d"}` **or** `{text}` (`HH:MM`, `dd.mm`, `dd.mm HH:MM`, `dd.mm.yyyy HH:MM`; a date keeps the current clock). Example: `misc.offer_due_request.json` | `{task: OfferTask}`; 400 `{detail, field: "due"}` (nothing / both given, unreadable, in the past); 403 not the assignee / a boss; 409 the task is not in `work`; 404 missing or out of the actor's scope | `design.services.set_design_due` / `price.services.set_price_due`: presets = N days after the later of the old deadline's day and today, same clock; `rev + 1`; emits `offer.changed` (`due_moved`, `to` = the assignee, `watchers` = the metering's manager when someone else moved it) **also for this bot-initiated action** |
| POST | `offers/{kind}/{id}/answer/` | `{answer, comment?}`: design `approved`\|`changes`\|`declined`; price `approved`\|`recalc`\|`declined`. `changes` / `recalc` / `declined` need a `comment` >= 3 chars. Example: `misc.offer_answer_request.json` | `{task: OfferTask, closed_tasks: int}` (example: `misc.offer_answer_response.json`); 400 `{detail, field: "answer"\|"comment"}`; 403 not the metering's manager (`ServiceForbidden`: its manager, a `manage_metering` holder or a superuser; with no manager set, any `metering.present_to_client` holder); 409 already answered / closed; 404 missing or out of scope | `design.services.record_design_answer` / `price.services.record_price_answer`. The client's answer is recorded by the manager. Design: `approved` -> only the design is marked approved (the price has been running since «Bajarildi»: design and price start at the same time); `changes` -> back to the same designer (round + 1, deadline = now + `DESIGN_FIX_DAYS` at `OFFER_DUE_HOUR`; the bot cannot pick a date, the designer moves it); `declined` -> the lead is closed «Rad etdi», its call tasks are closed (`closed_tasks`, `crm.task_closed` auto), the price is cancelled. Price: `approved` -> `metering.client_result="agreed"` + `offer.order_ready`; `recalc` -> back to the pricer (`PRICE_FIX_DAYS`); `declined` -> lead answer «Narx muammosi» (`price_problem`). Emits `offer.changed` (`answered`) **also for bot-initiated answers** |
| POST | `rovers/{id}/confirm/` | `{}` | `{rover: RoverTask}` (example: `misc.rover_confirm_response.json`); 403 not linked / no `oauth.user_rover_checker`; 409 already confirmed; 400 the worker has not handed it in yet; 404 missing | `order.rover.services.confirm_rover`: `done=True`, `checked_at/by`, the painter is notified; emits `rover.checked` **also for this bot-initiated action** |
| POST | `rovers/{id}/submit/` | `{amount: str\|number, note: str}` (example: `misc.rover_submit_request.json`) | `{rover: RoverTask}` (example: `misc.rover_submit_response.json`); 403 not linked / no `rover.change_rover`; 400 `{detail, field: "amount"}` (not a number, <= 0, > 12 digits) or `{detail, field: "note"}` (not a string, < 3 or > 2000 chars after strip); 409 already handed in / done; 404 missing | `order.rover.services.submit_rover`: the worker's «Bajardim» — amount replaces the price, `note` stored, state -> `checking`; emits `rover.check` |
| POST | `rovers/{id}/due/` | `{days: int 1..30}` (example: `misc.rover_due_request.json`) | `{rover: RoverTask}` (example: `misc.rover_due_response.json`); 403 not linked / no `oauth.user_production_head`; 400 `{detail, field: "due"}` (missing, not an int, outside 1..30); 409 rover done; 404 missing | `order.rover.services.set_rover_due`: `due_date = today + days`, `due_auto=false`, `due_set_by`; emits `rover.due_set` (not emitted when the date is unchanged) |
| POST | `painters/{id}/done/` | `{note: str}` (example: `misc.painter_done_request.json`) | `{painter: PainterTask}` (example: `misc.painter_done_response.json`); 403 not linked / not the job's molyar and no `painter.change_painter`; 400 `{detail, field: "note"}` (not a string, < 3 or > 2000 chars after strip) or rover not finished; 409 already done; 404 missing | `order.painter.services.mark_painter_done`: the molyar's «Bajardim» - izoh only, the job is done at once (price stays automatic: type.price x square); emits `painter.done` **also for this bot-initiated action** |
| POST | `painters/{id}/due/` | `{days: int 1..30}` (example: `misc.painter_due_request.json`) | `{painter: PainterTask}` (example: `misc.painter_due_response.json`); 403 not linked / no `oauth.user_production_head`; 400 `{detail, field: "due"}` (missing, not an int, outside 1..30); 409 job done; 404 missing | `order.painter.services.set_painter_due`: `due_date = today + days`, `due_auto=false`, `due_set_by`; emits `painter.due_set` (not emitted when the date is unchanged) |
| POST | `painters/{id}/type/` | `{type_id: int}` (example: `misc.painter_type_request.json`) | `{painter: PainterTask}` (example: `misc.painter_type_response.json`); 403 not linked / no `oauth.user_production_head`; 404 painter missing or `type_id` missing/not an int/unknown ("Molyar yoki jamoa topilmadi"); 400 rover not finished / the team has no molyar; 409 job done, or a different team is already chosen and the job started ("Jamoa allaqachon tanlangan: … — o'zgartirish saytda"; changing is site-only) | `order.painter.services.assign_painter_type`: the head picks the team; the first pick starts the job (`painter.task` to the team's molyar, `painter.due_ask` to the heads unless a deadline is already set). Re-picking the current team is an idempotent 200 (starts a legacy row that never started); the bot cannot change a started team |
| POST | `assemblies/{id}/finish/` | `{note: str}` (example: `misc.assembly_finish_request.json`) | `{assembly: AssemblyTask}` (example: `misc.assembly_finish_response.json`); 403 not linked / not the job's assembler and no `assembly.change_assembly`; 400 `{detail, field: "note"}` (not a string, < 3 or > 2000 chars after strip) or the order is not in assembly yet; 409 already finished or already waiting for the head's check; 404 missing | `order.assembly.services.finish_assembly`: the assembler's «O'rnatildi» - izoh only; sets `done` and the finish fields, the job goes to `state: "checking"` (the order moves ASSEMBLY -> INSTALLING, it does **not** become «Tayyor» yet); emits `assembly.done` (= «o'rnatildi, tasdiqlang») **also for this bot-initiated action** |
| POST | `assemblies/{id}/confirm/` | `{}` | `{assembly: AssemblyTask}` (state `done`; example: `misc.assembly_confirm_response.json`); 403 not linked / no `oauth.user_production_head`; 400 the assembler has not pressed «O'rnatildi» yet; 404 missing; 409 already done | `order.assembly.services.confirm_assembly`: the head's «Tayyor» - one transaction sets `installing_done`, `confirmed_at/by` and the order «Готов» (accounting `order_ready` chain fires as before); emits `assembly.confirmed` |
| POST | `assemblies/{id}/due/` | `{days: int 1..30}` (example: `misc.assembly_due_request.json`) | `{assembly: AssemblyTask}` (example: `misc.assembly_due_response.json`); 403 not linked / no `oauth.user_production_head`; 400 `{detail, field: "due"}` (missing, bool, not an int, outside 1..30); 409 job finished; 404 missing | `order.assembly.services.set_assembly_due`: `due_date = today + days`, `due_auto=false`, `due_set_by`; emits `assembly.due_set` (not emitted when the date is unchanged) |
| POST | `assemblies/{id}/assembler/` | `{user_id: int}` (example: `misc.assembly_assembler_request.json`) | `{assembly: AssemblyTask}` (example: `misc.assembly_assembler_response.json`); 403 not linked / no `oauth.user_production_head`; 404 job missing or `user_id` missing/not an int/unknown/not an active assembler ("Yig'ish yoki yig'uvchi topilmadi"); 400 detailing not finished; 409 job finished or handed in («O'rnatildi», waiting for the head), or a different assembler is already chosen and the job started ("Jamoa allaqachon tanlangan: … — o'zgartirish saytda"; changing is site-only) | `order.assembly.services.assign_assembler`: the head picks the assembler; the first pick while the order is in «Сборка» starts the job (`assembly.task` to the assembler, `assembly.due_ask` to the heads unless a deadline is set). Re-picking the current assembler is an idempotent 200 (starts a legacy row that never started) |

**Task outcomes** (completing a task asks "which stage does the lead go to?"). `outcome` is the next stage as a key of the lead board: `re_phone`, `given_info`, `given_location`, `go_for_measured`, `price_problem`, `dont_need`, `declined`, `keep`.

1. The backend alone decides which are allowed (`task_outcomes`, returned as `outcomes` by `GET crm/tasks/{id}/`). A closed lead (answer in sold_out / go_for_measured / price_problem / dont_need / declined) or an actor without `call_center.change_invoice` gets `["keep"]` (the task is closed, the stage does not change; `outcome` may then be omitted or `"keep"`). An active lead (new / re_phone / given_info / given_location) gets `[re_phone, given_info, given_location, go_for_measured (only with metering.add_metering), price_problem, dont_need, declined]`; `keep` is NOT offered there (to stay on the stage, pick it).
2. When `outcomes != ["keep"]` an `outcome` is required: missing or not allowed = 400 `{detail: "Keyingi bosqichni tanlang" \| "Bu bosqichni tanlab bo'lmaydi", field: "outcome"}`.
3. `go_for_measured` is never accepted by `done`: 400 «O'lchov yarating — javob kodi avtomatik o'zgaradi», `field: "outcome"`. The client creates the metering first (the stage then changes by itself and the lead is served: `keep` only), then completes the task with `keep`. The bot sends the user to the panel with a URL button.
4. `next_task` (the next call): required for `re_phone` (400 «Qayta qo'ng'iroq vaqtini ko'rsating», `field: "next_task"`); optional for `given_info` / `given_location`; forbidden for `price_problem` / `dont_need` / `declined` / `keep` (400 «Yopilgan arizaga vazifa qo'shib bo'lmaydi», `field: "next_task"`). Exactly one of `preset` / `due_at`; `due_at` must be in the future (400 «O'tgan vaqt — kelajakdagi vaqtni kiriting», `field: "next_task"`); a malformed `next_task` = 400 `field: "next_task"`. The new task is assigned to the lead's owner (fallback: the actor), default text «Mijozga qo'ng'iroq qilish»; presets as in `snooze` plus `today` (18:00, or +1 h after 17:00).
5. A closing outcome (`price_problem`, `dont_need`, `declined`) also closes the lead's other open tasks (`closed_tasks` = how many; the same happens on any solution change to those answers, e.g. a board drag) and the history line gets `meta.closed_tasks`. Choosing the lead's current stage writes no history line.


**Ombor (warehouse keeper)** - the actor is the panel user whose `oauth.User.telegram_id` is the `X-Bot-Actor`, and must be THE keeper (`WarehouseConfig.keeper`). Not linked: 403 `{detail: "Telegram saytdagi profilingizga ulanmagan"}`; linked but not the keeper: 403 `{detail: "Ombor faqat omborchi uchun."}`. `ServiceError` = 400 `{detail, field?}` (`field`: `name|code|unit|min_quantity|quantity|unit_price|orig_price|allocations|kind|currency|rate|date|period|file|product`; input validation of the request body may name **any request field** of that endpoint, so the bot must treat `field` as open-ended and fall back to showing `detail`). A photo/movement record that vanished concurrently is a 404, `ServiceConflict` = 409. Business rules: `warehouse/services.py`. Limits: at most **5 photos** per product, upload at most **10 MB**, jpeg/png/webp only (HEIC is refused with a 400 `field: "file"`); the backend re-encodes every upload to a JPEG of at most 1600 px (plus a 400 px thumb), EXIF is dropped. `tg_file_id` is only a cache. A **chiqim has no price from the bot**: the backend takes the product's `avg_cost` under the row lock. A kirim needs `unit_price` (UZS) or `orig_price` (USD, rate = Moliya rate). Movements from the bot are dated today. Page size is 8.

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `warehouse/meta/` | - | `{units: [{value, label}], categories: [str] (distinct, sorted, max 40), usd_rate: "12650.0000", max_photos: 5}` |
| GET | `warehouse/products/?q=&low=0\|1&inactive=0\|1&page=1` | - | `{items: [WhProduct], page, pages, total}`; `q` matches name / code / category (icontains, an exact code first); inactive products only with `inactive=1` |
| POST | `warehouse/products/` | `{name, unit, category?, code?, min_quantity?}` | 201 `{product: WhProduct+photos}`; 400 `field: name\|code\|unit\|min_quantity` |
| GET | `warehouse/products/{id}/` | - | `{product: WhProduct+photos, last_in: {unit_price, currency, orig_price, counterparty, date}\|null, recent: [WhMovement] (5, newest first)}` (example: `misc.wh_product_detail_response.json`); 404 |
| PATCH | `warehouse/products/{id}/` | any of `name, code, category, unit, min_quantity, is_active` | `{product: WhProduct+photos}`; 400 as POST; 404 |
| POST | `warehouse/products/{id}/photos/` | multipart (see 2.3) | 201 `{photo: WhPhoto, product: WhProduct+photos}`; 400 `field: "file"` (not an image, HEIC, too big, 5 already) |
| DELETE | `warehouse/photos/{id}/` | - | `{product: WhProduct+photos}` (the rest are renumbered 0..n-1); 404 |
| POST | `warehouse/photos/{id}/cover/` | `{}` | `{product: WhProduct+photos}`; 404 |
| GET | `warehouse/photos/{id}/file/` | - | raw `image/jpeg` (the main file, at most 1600 px); 404 |
| POST | `warehouse/photos/{id}/tg-file/` | `{file_id}` | 204 (caches the Telegram file_id); 404 |
| GET | `warehouse/movements/?product={id}&page=1` | - | `{items: [WhMovement], page, pages, total}` newest first, cancelled included |
| POST | `warehouse/movements/` | `{product, kind: "in"\|"out", quantity?: "12.5", allocations?: [{ref, quantity}], currency?: "UZS"\|"USD", unit_price?, orig_price?, counterparty?, comment?}` (example: `misc.wh_movement_request.json`) | 201 `{movement: WhMovement, product: WhProduct+photos}` (example: `misc.wh_movement_response.json`); 400 `field: quantity\|unit_price\|orig_price\|allocations\|product`; 404 unknown product | Chiqim to clients: `allocations` (max 20 lines, `quantity` per ID, a chiqim only - on a kirim 400 `field: "allocations"`) - ONE movement, stock goes down by the sum; `quantity` may be omitted (= the sum) and must equal it when sent (else 400 `field: "quantity"`); an unknown ref or the same ID twice is 400 `field: "allocations"`; the sum above the stock is 400 `field: "quantity"` and nothing is written. Each line is counted as that order's furnitura (see OrderCard `stats.warehouse`). Cancelling the movement cancels every line.
| GET | `warehouse/orders/?q=` | - | `{items: [WhOrderRef]}` (max 24): active orders (`jarayonda, yangi, kutish, yakun` + open manual orders) whose ID or client contains `q`; an exact ID of a finished order is listed first |
| POST | `warehouse/orders/resolve/` | `{text}` (IDs split on spaces / commas, `#` ignored; example: `misc.wh_orders_resolve_request.json`) | `{items: [WhOrderRef], unknown: [str]}` (example: `misc.wh_orders_resolve_response.json`) |
| POST | `warehouse/movements/{number}/cancel/` | `{}` | `{movement, product}`; 409 already cancelled; 400 when the stock would go negative; 404 |
| GET | `warehouse/summary/?period=today\|week\|month` | - | `{period, start, end, products, stock_value, usd_rate, low_count, period_in, period_out}` (example: `misc.wh_summary_response.json`); 400 `field: "period"` |

**Finance: reads**

| Method | Path | Response / rule | Replaces |
|---|---|---|---|
| GET | `finance/config/` | `{channel_id, usd_rate, usd_rate_manual, ready_days, version}` | `config.*`, `S.usd_rate` |
| GET | `finance/members/?set=staff\|wallets\|pending\|active&duty=<field>` | `[Member]` | `S.staff`, `S.wallets`, pending `router.py:1209`, `role_pick` `:1879-1880` |
| GET | `finance/members/{tg}/` | `Member` (admin, or self) | `S.member_by_tg` (targets of /ism, nudge, give, trto, approve) |
| GET | `finance/members/{tg}/balance/` | `{balance}` (self, or admin) | `S.balance` |
| GET | `finance/categories/?kind=` | `[Category]` | `S.categories`, `S.category` |
| GET | `finance/workers/` | `[Worker]` (active) | `Worker.objects` `:749/:820/:847/:867/:2069`; group labels / team logic move to bot |
| GET | `finance/cars/` | `[Car]` | `:920`, `:2084` |
| POST | `finance/parse/` | `{text, mode: "quick"\|"money"}` → quick `{kind, val, cur, cat, ord, com}\|null`; money `{amount, cur, orig, rate}\|null` (400 when no rate) | `parse_quick` / `parse_money` / `S.money_in`; parsers stay in `accounting/text.py` |
| GET | `finance/orders/?buckets=a,b` | `[OrderBrief]` | `S.open_orders` |
| GET | `finance/orders/archive/` | `[OrderBrief]` | `S.archive_orders` |
| GET | `finance/orders/closed-manual/` (admin) | `[OrderBrief]` | `:2191` |
| GET | `finance/orders/next-ref/` (admin) | `{ref}` | `S.next_manual_ref` |
| GET | `finance/orders/{ref}/` | `OrderCard` / 404 | `S.order_info` + `S.order_stats` (also `order_line` / `ord_text`) |
| GET | `finance/summary/?month=&member=<tg\|all>` | `S.summary` + `member_balance`; non-admins forced to self | `info()` `:1024` |
| GET | `finance/operations/?month=&member=` | `{rows: [Operation + signed_amount + internal]}`; bot paginates | `ops()` `:1102` |
| GET | `finance/operations/{n}/` | `Operation + can_delete + can_attach` | `:1004`, `:2162`, `:2170` |
| GET | `finance/months/?member=` | `S.months_series` | `months_view` |
| GET | `finance/wallets/` (admin) | `{report_month, rows: [{member, balance, last_day, reported, month_spent}], pending: [Member], staff_total}` | `wallets_view` `:1177` |
| GET | `finance/checks/` (admin) | `[issue]` | `S.checks` |
| GET | `finance/excel/?month=` (admin) | xlsx bytes + `Content-Disposition` | `month_xlsx` |
| GET | `finance/month-report/` | `{month, opening, income, expense, closing, count, submitted}` | `month_start` `:1641`; month choice → new `S.month_report_target(member)` |
| GET | `finance/month-report/excel/?month=&member=<tg>` | xlsx bytes + `Content-Disposition`; admins any member, staff only themselves | `month_submitted` notify (sent to each admin) |
| GET | `finance/handover/` (admin) | `[Operation]` | `S.handover_pending` |
| GET | `finance/advances/` (admin) | `[Advance]` (pending) | `OrderAdvance` |
| POST | `finance/advances/{id}/accept/` (admin) | `{amount_text?}` → `{advance, balance}`; `amount_text` = the boss got another amount («4.5 mln», «450$»); 409 if answered | `S.advance_accept` (kirim «Avans» into the boss's cash + the order's «Полученная сумма») | — |
| POST | `finance/advances/{id}/reject/` (admin) | → `{advance, balance}`; 409 if answered | `S.advance_reject` | — |
| GET | `finance/warranty/?given=0` (receiver/admin) | `[Warranty]` | `:1861` |
| GET | `finance/tasks/` | `{site_entry: [Task], feedback: [Feedback]}`, scoped by duties | `tasks_view` `:1910` |
| GET | `finance/requests/{n}/` (admin) | `MoneyRequest` | `:1592` |
| GET | `finance/bonuses/{ref}/?or_temp=1` | `{bonus, money_state, tolerance, is_receiver, usd_rate, percent_now}` | `bonus_paid_btn`, `_bonus_or_temp` `:540` |
| GET | `finance/bonuses/{ref}/card.png?or_temp=1` | PNG | `report_card_png` (stays in backend) |
| GET | `finance/feedback/{ref}/` | `Feedback`; 404 if none | `fikr_btn` `:1952` |

**Finance: writes** (each emits events from §1.5; the handler only replies in the current chat)

| Method | Path | Request → Response | Service | Events |
|---|---|---|---|---|
| POST | `finance/join/` | `{name, username}` → `{member, created}` | `S.register_member` | `finance.join_requested` (if created) |
| POST | `finance/operations/` | `{member_tg, kind, amount, category, currency, orig_amount, rate, order_ref, comment, receipt_file_id, worker, pay_type}` → `{operation, balance}`; `actor_admin` derived server-side; `pay_type` (salary only) is `Avans` / `Oylik` / `Uy uchun` — `Uy uchun` only when `worker` is an `is_boss` worker, else 400; non-admins always get `Avans`; an inactive category is refused (400) | `S.create_operation`, then `followup.bonus_check(ref, ok_hour=False)` for client payments | `operation_created` |
| POST | `finance/operations/{n}/receipt/` | `{file_id}` → Operation (admin or author) | new `S.attach_receipt(op, file_id, actor)` | `receipt_attached` |
| DELETE | `finance/operations/{n}/` | → `{deleted: [Operation]}` | `S.can_delete` + `S.delete_operation` | `operation_deleted` |
| POST | `finance/transfers/` | `{to_tg, amount, comment}` → `{out, inc, balance}` | `S.create_transfer` | `transfer_created` |
| POST | `finance/requests/` | `{amount_text, reason}` → MoneyRequest | `S.money_in` + `S.create_request` | `request_created` |
| POST | `finance/requests/{n}/give/` (admin) | `{amount_text\|null}` → `{request, operation, balance}`; 409 if answered | `S.give_request` | `request_answered` |
| POST | `finance/requests/{n}/reject/` (admin) | → request | `S.reject_request` | `request_answered` |
| POST | `finance/requests/{n}/admin-messages/` | `{messages: [[chat, mid]]}` → 204 | new `S.set_request_messages` | – |
| POST | `finance/month-report/` | `{month, note}` → `{report, summary}` | `S.submit_month` | `month_submitted` |
| POST | `finance/manual-orders/` (admin) | `{ref, client, phone, price_text}` → OrderBrief | `S.create_manual_order` | `manual_order_created` |
| PATCH | `finance/manual-orders/{ref}/` (admin) | `{price_text}` or `{toggle_closed: true}` → OrderCard | new `S.set_manual_price`, `S.toggle_manual_order` (replace `:1403`, `:2265`) | `manual_order_closed` |
| POST | `finance/bonuses/{ref}/collect/` (receiver) | `{amount_text, full}` → `{bonus, rest, full, operation, task}` | `S.bonus_collect` (a site order's «Полученная сумма» is raised at once, its task comes back already done) + `S.site_entry_create` | `site_entry_created` (manual orders only), `handover_requested` (actor not admin), `bonus_done` (if full) |
| POST | `finance/bonuses/{ref}/close/` (receiver) | → bonus; 400 if rest > tolerance | `S.bonus_finish` | `bonus_done` |
| POST | `finance/handover/{n}/accept\|drop/` (admin) | → `{operation, client, sum_text, member_balance}`; 409 if marked | `S.handover_accept` / `S.handover_drop` | `handover_resolved` |
| POST | `finance/warranty/{ref}/give/` (receiver) | → Warranty | `S.warranty_give` | `warranty_given` (actor not admin) |
| POST | `finance/site-entry/{code}/done/` (admin/site_entry) | → Task; 409 if done | `S.site_entry_done` | `site_entry_done` |
| POST | `finance/feedback/{ref}/` (admin/feedback), multipart | `file`, `file_id`, `caption` → Feedback | new `S.receive_feedback_photo(ref, by_name, caption, file_id, content)`: atomic get-or-create + storage save + `feedback_receive` (replaces `:1961-1977`) | `feedback_received` |
| POST | `finance/members/{tg}/name/` (admin) | `{name}` → Member | new `S.rename_member` | – |
| POST | `finance/members/{tg}/role/` (admin) | `{role: staff\|blocked}` → Member | `S.set_member_role` | `member_approved` (staff) |
| POST | `finance/members/{tg}/duty/` (admin) | `{duty}` → Member | `S.set_duty_exclusive` | `duty_assigned` |
| PUT | `finance/config/usd-rate/` (admin) | `{rate}` → config | new `S.set_usd_rate` | – |
| POST / DELETE | `finance/report-template/` (admin) | multipart `file` → 204 | new `S.set_report_template(bytes)` / `S.reset_report_template()` (replace `:535`, `:1997`) | – |

**HR** (actor = Telegram id; "admin" = `hr.services.is_admin`)

| Method | Path | Request → Response | Service (new in `hr/services.py` unless noted) |
|---|---|---|---|
| POST | `hr/group-message/` | `{chat: {id, title, username}, message_id, date, from, forwarded, media: {video_note, photo, video, location, venue}, text}` → `{action: ignored\|checkin\|checkout\|leave_only\|format_warning, react: emoji\|null, reply: {status, at, late_min}\|null, dm: {kind: checkin_on_time\|checkin_late\|checkout\|checkout_early\|leave_without_checkin\|format_warning, employee, day, at, late_min, early_min, end, uniform_ask}\|null}` | `process_group_report(...)` (port of `on_group_message` / `on_checkout`, `hr/telegram.py:280-434`); emits `hr.live_alert` |
| POST | `hr/members/joined/` | `{chat, users: [user]}` → `{welcome: [{name}]}` | `members_joined` |
| POST | `hr/members/left/` | `{chat, user}` → `{}` | `member_left` (emits `hr.employee_left`) |
| POST | `hr/bot-membership/` | `{chat, status}` → `{}` | emits `hr.bot_added_to_group` if group is new |
| GET | `hr/groups/` | `[WorkGroup]` | `S.groups` |
| POST | `hr/groups/` (admin) | `{chat_id, title}` → WorkGroup | `connect_group` (`/ulash`); getMe / getChatMember check stays in bot |
| DELETE | `hr/groups/{chat_id}/` (admin) | 204 | `disconnect_group` (`/uzish`) |
| POST | `hr/employees/` (admin) | `{user, chat_id}` → Employee | `S.upsert_emp` (`/qosh`) |
| POST | `hr/start/` | `{user, group_chat_id\|null}` → `{employee\|null}`; bot first does getChatMember over `hr/groups/` | `employee_start` (sets `can_dm` / `is_active`) |
| GET | `hr/me/status/` | `{employee, today: {st, in_time, out_time}, month: {rank, of, pts, on_time, late, late_min, absent, excused, early_n, disc}\|null}` | `my_status_data` |
| POST | `hr/cant-come/` | → `{result: not_employee\|already_in\|ask_reason, day}` | `/kelolmayman` |
| POST | `hr/private-text/` | `{text}` → `{handled, outcome: late_comment\|early_comment\|excused\|eta\|null, data: {late_reason, early_reason, eta, uniform_ask}}` | `process_private_text` (port of `:635-714`, incl. `_looks_finance`); emits alerts |
| POST | `hr/callback/` | `{action: uni\|lr\|er\|eta\|here\|cant\|rsn\|offreq, day, arg}` → `{answer, alert, clear_kb, reply: {kind, data}\|null}` | `process_employee_callback` (port of `:768-875`); emits `hr.off_request` / alerts |
| POST | `hr/dm-status/` | `{telegram_id, ok, blocked}` → 204 | `record_dm(tg, ok, blocked)` (replaces `can_dm` updates `:87/:95/:256/:779`) |
| GET | `hr/reports/day/?date=` (admin) | `DayReportData` (`{kind: live\|past, …}`) | `hr/report_data.py` |
| GET | `hr/reports/period/?from=&to=` (admin) | `PeriodReportData` | `hr/report_data.py` |
| GET | `hr/ranking/?month=\|year=` (admin) | `[{employee, pts, disc, bonus, adj, wins}]` | `S.month_stats` / `S.year_stats` |
| GET | `hr/employees/?active=` (admin) | `[Employee]` | `S.all_emps` / `S.active_emps` |
| GET / PATCH | `hr/employees/{ref}/` (admin; ref = № or tg) | PATCH `{off_days\|"general", toggle_off_day, work_start, work_end, reset_hours, is_active}` | `S.find_emp`, `S.set_hours`, new `set_off_days` / `toggle_off_day` / `set_active` (replace `:1017`, `:1089`, `:1416`) |
| POST | `hr/employees/{ref}/notify/` (admin) | `{what: off_days\|hours}` | emits `hr.off_days_set` / `hr.hours_set` |
| POST | `hr/day-off/` (admin) | `{employee, date}`; dates parsed server-side by `S.parse_date` (`bugun` / `dd.mm[.yyyy]`) | `S.set_att(status="off")`; emits `hr.day_off_set` |
| GET / POST / DELETE | `hr/leaves/` / `hr/leaves/{number}/` (admin) | `{employee, date_from, date_to, reason}` | `S.add_leave`, new `delete_leave`; emits `hr.leave_added` |
| GET / POST / DELETE | `hr/holidays/` / `hr/holidays/{day}/` (admin) | `{day, name}` | new `set_holiday` / `delete_holiday` |
| GET / POST | `hr/holidays/{day}/decision/` (admin) | `{n, start}` → `{days, name}`; 409 if decided | `S.apply_holiday`; emits `hr.holiday_applied` |
| GET / PUT | `hr/settings/` / `hr/settings/{key}/` (admin) | `[{key, label, value}]` / `{value}` | `S.all_settings`, `S.set_setting` |
| POST | `hr/points/` (admin) | `{employee, value, reason}` | `S.add_points`; emits `hr.points_added` |
| POST | `hr/reset/` (admin) | `{since}` | `S.reset_data` |
| POST | `hr/winners/` (admin) | `{kind, period, employee_tg}` → `{groups_count}`; 409 if announced | new `announce_winner` (atomic Winner create + stats); emits `hr.winner_announced` |
| POST | `hr/off-requests/` (admin) | `{employee_tg, day, approve}` | `S.set_att`; emits `hr.off_request_answered` |

### 1.4 Bot HTTP routes (`bot/api/routes.py`)

- `POST /notify` (signed): envelope `{"id": uuid, "event": str, "data": {...}}` → `200 {"ok": true, "delivered": [{chat_id, ok, message_id, error_code, blocked}]}`.
  - Dedup: `SET NX dedup:evt:{id} EX 86400`; duplicate → `200 {"ok": true, "duplicate": true}`.
  - Unknown event or bad data → `400`; backend does not retry.
  - Telegram 403 / "chat not found" is still `200` with `blocked: true`.
- `GET /files/{file_id}` (signed): bytes + `Content-Type`; `404` when Telegram can't serve it. Replaces the backend's `download_file`.
- `POST /webhook`: unchanged (Telegram `secret_token`).
- `POST /user/{chat_id}/message` (`oauth.User.send_message`): body `{text, url}`, now **signed** like `/notify` (same headers, actor empty); 403 without a valid signature.
  - The ASSEMBLY («Сборка») status change no longer sends a Telegram `send_message` to `view_assembly` holders (the `assembly.ready` / `assembly.task` cards replace it; the SMS stays only for holders without Telegram), and creating an Assembly row (at detailing) sends nothing.

### 1.5 Event catalogue (backend → bot)

Every event carries computed recipients (`to` / `admins` / `channel_id` / `groups`). Duty events carry `fallback: bool` + `fallback_who`; the bot renders the «⚠️ … belgilanmagan» prefix that `notify_to` uses today.

| Event | Data | Emitted from |
|---|---|---|
| finance.operation_created | `operation, balance, from_site, notify_owner, owner_tg, channel_id` | bot `finance/operations/`; site `OperationViewSet` create (`finance.py:280`) |
| finance.operation_edited | `operation, balance, before{kind_label, amount, category_name}, by_name, pair{operation, balance}\|null, channel_id` | site edit (`:298`) |
| finance.operation_deleted | `operations, by_name, channel_id` | bot delete; site delete (`:311`) |
| finance.receipt_attached | `operation, file_id, channel_id` | bot receipt |
| finance.transfer_created | `out, inc, inc_balance, inc_member, admins (excl. author), channel_id` | bot; site transfer (`:358`) |
| finance.join_requested | `member, admins, superusers` (superusers only when no admins) | bot join |
| finance.member_approved | `member` | bot approve; site `TelegramMemberViewSet.perform_update` (`:182`) |
| finance.duty_assigned | `member, duty` | bot `/saytchi`, `/fikrchi` |
| finance.request_created | `request, admins` (bot then POSTs `admin-messages`) | bot |
| finance.request_answered | `request, status: given\|rejected, by_name, from_site, operation\|null, balance, post_to_channel, channel_id` | bot give/reject; site `:756`, `:774` (site: `post_to_channel=false`) |
| finance.month_submitted | `member, month, summary, note, closing, admins, channel_id` (bot then GETs `finance/month-report/excel/` per admin) | bot |
| finance.manual_order_created / manual_order_closed | `order, spent, channel_id` | bot |
| finance.handover_requested | `operation, who, ref, client, sum_text, rest_text, admins` | bot collect |
| finance.advance_requested | `advance: Advance, admins` — a new order came with an advance: the boss presses «✅ Pulni qabul qildim» / «✏️ Boshqa summa oldim» / «❌ Pul kelmadi» (`finance/advances/{id}/accept|reject/`) | order create (site) |
| finance.handover_resolved | `operation, action, client, sum_text, member_balance` | bot |
| finance.warranty_given | `letter, by_name, admins` | bot |
| finance.site_entry_created | `task, collector_name, to, fallback` | bot collect |
| finance.site_entry_done | `task, by_name, admins` | bot; site (`:854`) |
| finance.feedback_received | `feedback, by_name, caption, file_id, admins` | bot |
| finance.bonus_done | `bonus, to, fallback, also_admins` | bot; site close (`:811`); followup |
| finance.ready_card | `bonus, money_state, usd_rate, to, fallback` (bot GETs `card.png`) | `followup.new_ready_orders` |
| finance.bonus_zero / bonus_term_reminder | `bonus, money_state\|rest, percent, days\|label, pct, to, fallback` | `followup.bonus_check` |
| finance.feedback_ask / feedback_remind | `feedback, to, fallback` | `followup.feedback_check` |
| finance.site_entry_remind | `task, to, fallback` | `followup.site_entry_remind` |
| finance.warranty_remind | `letter, ready_date, days, step (3\|7\|15\|30), to, fallback, fallback_who, also_admins` — the warranty letter is still not handed `days` after Готов: the bonus receivers (admins when nobody is) get «📜 Kafolat xati berdim» (`kfx:{ref}`); from step 15 the non-receiver admins too. Only the latest step reached, each once | `followup.warranty_remind` (hourly, 9–21, ≤10 per pass; only Готов on/after `FIN_WARRANTY_SINCE`, set to the first run day) |
| finance.deadline | `order{ref, client, end_date, status_label, phone, address, lat\|null, lon\|null, map_url\|null}, left_days, key, to, fallback` | `followup.deadline_reminders` |
| finance.salary_due | `workers[{id, name, group, position, pay_date, has_template}], to, fallback, fallback_who` — tomorrow is these workers' pay day: «oylik chiqarish kerak» to the accountant (`is_accountant`; the admins when nobody is) | `salary.remind` (celery `accounting.tasks.salary_reminder`, 10:00, once per worker + pay date) |
| finance.daily_reminder | `member, balance` (one event per person) | `jobs.daily_reminder` |
| finance.month_end_reminder / month_late | `member, left_days\|month, balance` | `jobs.month_job` |
| finance.month_late_admins | `month, names, admins` | `jobs.month_job` |
| finance.admin_daily | `date, summary, ops_count, by_member, silent, checks{count, high}, month, admins` | `jobs.admin_daily` |
| finance.month_excel | `month, admins` (bot GETs `finance/excel/`) | `jobs.admin_daily` on the 1st |
| hr.morning | `chat_id, starts, uniform_check` | `hr/jobs` step 1 |
| hr.ask_eta | `employee, start, day, repeat` (**sync**) | steps 2 and 4 |
| hr.missing_list | `chat_id, names` | step 2 |
| hr.out_reminder | `employee` (sync) | step 4b |
| hr.eta_passed | `employee, eta, day` (sync) | step 5 |
| hr.day_report | `admins, now_hm, report: DayReportData` | step 6 |
| hr.month_report | `admins, ym, report: PeriodReportData, site_url` | step 7 |
| hr.winner_pick | `admins, kind: m\|y, period, rows (top 3 carry tg)` | step 7 |
| hr.holiday_ask | `admins, day, name` | `ask_holidays` |
| hr.birthday | `employee, day, age\|null` — the employee's birthday: the bot congratulates them privately on behalf of HR; if the DM fails, in their work group | `hr/jobs.birthdays` (step 9, from `BIRTHDAY_TIME`, once per day) |
| hr.birthday_soon | `employee, day, left_days, age\|null, to, fallback` — the birthday is in `left_days` (3): «Bosh menejer» users with Telegram (`fallback`=true: the admins) | `hr/jobs.birthdays` |
| hr.live_alert | `admins, kind: late\|late_comment\|eta\|excused, employee, data` | group-message, private-text, callback |
| hr.off_request / off_request_answered | `admins\|employee, day, approve` | callback / admin |
| hr.employee_left / bot_added_to_group | `admins, name\|title` | membership |
| hr.points_added | `employee, value, reason, from_site` | bot `/ball`; site `PointAdjustmentViewSet.perform_create` (`hr.py:204`) |
| hr.winner_announced | `kind, period, employee, pts, disc, groups` | bot `ann`; site `WinnerViewSet.announce` (`hr.py:245`) |
| hr.holiday_applied | `hol_day, name, n, days, admins, groups` | bot |
| crm.task_due | `task: CrmTask, invoice: LeadBrief, to: [tg], url` | Celery `call_center.tasks.task_reminders` (every minute): every open, not yet notified task whose `due_at` has come, once per task + reschedule (`accounting.services.once` keyed `cc:task:{id}:{remind_seq}`); `to` = the assignee's Telegram id; `url` = `{ADMIN_BASE_URL}/call-center?open={invoice id}` |
| crm.task_closed | `task: {id}, how: "done"\|"auto", by_name: str\|null, solution_label: str\|null, next_due: "YYYY-MM-DDTHH:MM:SS"\|null, to: [tg]` | A reminder the bot may already have sent was closed outside the bot. `done` = finished in the panel (`call_center.services.complete_task`, `via="panel"`; `next_due` = the follow-up call it created); `auto` = closed because its lead got a closing answer (`_close_open_tasks`, from panel, bot or board; one event per task). **Not emitted for the task a bot request itself completes** (bot `done`): the bot edits its own message. The bot removes the buttons from the stored reminder and appends a status line; no stored reminder = no-op. `to` = the assignee's Telegram id (informational, `[]` when unlinked) |
| crm.task_moved | `task: {id, due_at}, how: "rescheduled"\|"reassigned", by_name: str\|null, to_name: str\|null, to: [tg]` | `rescheduled` = moved in the panel (`reschedule_task`, `due_at` = the new time; a fresh `crm.task_due` follows at that time); `reassigned` = the lead's open tasks followed a new owner (`update_lead`; `to_name` = new owner, `to` = the previous assignee's Telegram id whose reminder is stale). Not emitted for the bot's own snooze. The bot strips the buttons and appends a status line |
| metering.assigned | `metering: MeteringBrief, how: "new"\|"reassigned", to: [tg]` | `metering.services.create_metering` (`new`) / `set_metering_measurer` (`reassigned`), after commit. `to` = the new measurer's Telegram id; not emitted (and an SMS is queued instead) when the measurer has no linked Telegram. The bot sends the assignment card with «✅ O'lchov oldim / 🕒 Vaqtni o'zgartirish / ❌ Bekor bo'ldi», remembers it (per card `{chat_id, message_id, kind}`; the last applied `rev` is stored separately per metering in `met:ver:{id}`) and edits it on later `metering.changed` |
| metering.reminder | `metering: MeteringBrief, kind: "soon"\|"late", to: [tg]` | Celery `metering.tasks.metering_reminders` (every minute), once per metering + `rev` + kind (`accounting.services.once` keyed `met:{id}:r{rev}:{kind}`). `soon` = about `METERING_REMIND_BEFORE_MIN` (60) before `date_time` (only when the measurer was told earlier than that); `late` = no answer `METERING_LATE_AFTER_MIN` (60) after `date_time` (within 24 h). Only for open (`created` / `other_day`) meterings of active measurers with Telegram |
| metering.digest | `date: "YYYY-MM-DD", items: [MeteringBrief] (by time), to: [tg], url` | the same job, from `METERING_DIGEST_HOUR` (20:00), once per measurer per day (`met:digest:{date}:{user}`): the measurer's open meterings of **tomorrow**; `url` = `{ADMIN_BASE_URL}/meterings?tab=tomorrow`. The bot does not store this message |
| metering.changed | `metering: MeteringBrief, how: "measured"\|"rescheduled"\|"done"\|"cancelled"\|"reassigned", by_name: str\|null, to_name: str\|null, to: [tg], watchers: [tg]` | every metering service write, **including actions the bot itself requested** (`measured`, `rescheduled`, `cancelled` through `meterings/{id}/...`). `to` = the measurer whose earlier messages are now stale (for `reassigned` the **previous** measurer; `to_name` = the new one); `watchers` = the operator, only for `rescheduled` and only when they are not the actor. `done` = the measurer pressed «Bajarildi» on the site (files + note + next step; `metering.next_step` is set) |
| offer.assigned | `task: OfferTask, how: "new"\|"reassigned"\|"changes", comment: str\|null, to: [tg]` | The designer / pricer got a task. `new` = the measurer pressed «Bajarildi» (the design and the price, or only the price) or the legacy create buttons; `reassigned` = `set_designer` / `set_pricer` / `assign_metering_tasks`; `changes` = the client asked for changes / a recalculation (`comment` = what to change, `task.round` + 1, new `task.due_at`); (the old `started` is gone: design and price start together on «Bajarildi», each assignee gets `new` at once. The backend never sends `started` now; the bot may keep its text for it.) `to` = the assignee's Telegram id; not emitted (an SMS is queued instead) without Telegram. Owner's rule: the price is the managers' job, there is no separate «Narxchi»; «Bajarildi» gives the price to the chosen manager. The bot sends the card with a deadline and «🕒 Muddatni o'zgartirish» / «🌐 Saytda ochish». **There is no «Tayyor» button: «Tayyor» is pressed on the site only.** The bot remembers the card per (kind, id) with role `work` |
| offer.reminder | `task: OfferTask, kind: "soon"\|"late"\|"overdue", to: [tg]` | Celery `metering.tasks.offer_reminders` (every minute), once per (kind, id) + `rev` (`accounting.services.once`: `off:{d\|p}:{id}:r{rev}:soon` / `late` / `od:{date}`). Only for tasks in `work` with a deadline and an active assignee with Telegram. `soon` = `OFFER_REMIND_HOUR` (09:00) the day before the deadline when it was assigned >= 36 h before it, else 09:00 on the deadline day (a deadline before 09:00: deadline - 2 h), only if it was assigned before that moment; `late` = the deadline passed (within 24 h); `overdue` = every morning at `OFFER_REMIND_HOUR` for 7 days |
| offer.present | `task: OfferTask, how: "ready"\|"reminder", to: [tg]` | The manager must show the design / price to the client. `ready` = the designer / pricer pressed «Tayyor» (to the metering's manager; a legacy metering without one: the only manager if exactly one, else nobody) **plus every «Bosh menejer»** (active staff holding `metering.manage_metering` explicitly, with Telegram; a copy of `ready` only, never of `reminder`; they may answer too). `reminder` = no answer `PRESENT_REMIND_HOURS` (24) after `ready`, then daily at `OFFER_REMIND_HOUR` for 7 days (`off:{k}:{id}:r{rev}:pr`, `pr:{date}`). The bot sends the manager card with the answer buttons (design «✅ Tasdiqladi / ✏️ O'zgartirish kerak / ❌ Rad etdi»; price «✅ Rozi / 🔁 Qayta hisoblash / ❌ Narxi qoniqtirmadi») and remembers it with role `present` |
| offer.changed | `task: OfferTask, how: "done"\|"due_moved"\|"reassigned"\|"answered"\|"cancelled", answer: str\|null, by_name: str\|null, to_name: str\|null, to: [tg], watchers: [tg]` | every offer service write, **including actions the bot itself requested** (`due_moved`, `answered`). `to` = the chats whose cards are now stale: `done` = the designer / pricer pressed «Tayyor» (their card becomes «menejerga yuborildi»); `due_moved` = the assignee (keeps its buttons; `watchers` = the manager when someone else moved it); `reassigned` = the **previous** assignee (`to_name` = the new one); `answered` = the manager (`answer` = `approved`\|`changes`\|`recalc`\|`declined`); `cancelled` = a pricer whose price was cancelled by a declined design. **Every «Bosh menejer» is added to `to` for `answered`** (their copy of the «tayyor» card); the bot edits only cards it stored for a chat, so a chat without one is a no-op |
| offer.order_ready | `task: OfferTask (kind price), to: [tg], url` | The client agreed to the price: make the order. `to` = the manager when they hold `order.add_order`, else every active staff member holding `order.add_order` explicitly; **every «Bosh menejer» is always added**. `url` = `{ADMIN_BASE_URL}/orders/new?metering={id}[&design={design id}]` |
| rover.check | `rover: RoverTask (state checking), to: [tg], workers: [tg]` | The worker pressed «Bajarildi» with the actual amount: every active staff holding `oauth.user_rover_checker` (with Telegram) gets the card with «✅ Bajarildi» (`POST rovers/{id}/confirm/`) / «🌐 Saytda ochish». Not emitted (logged) when no checker has Telegram. The bot remembers the card per (rover id, chat) |
| rover.checked | `rover: RoverTask (state done), by_name: str, to: [tg], workers: [tg]` | A checker confirmed (panel or bot). `to` = the checkers: their cards are now stale. The bot edits **only the stored cards whose chat is in `to`**; no stored card = no-op |
| rover.task | `rover: RoverTask (state new), to: [tg]` | A new rover job (detailing set the rover square): every active staff holding `oauth.user_rover` (with Telegram) gets the full task card with «✅ Bajardim» (amount + izoh, `POST rovers/{id}/submit/`). Not emitted (logged) when nobody has Telegram. SMS goes to workers without Telegram (Celery `rover_task_sms`) |
| rover.due_ask | `rover: RoverTask, presets: [3,5,7], to: [tg]` | A new rover job: every active staff holding `oauth.user_production_head` (with Telegram) is asked for a deadline — buttons «+3 / +5 / +7 kun» (`POST rovers/{id}/due/ {days}`). Not emitted when no head has Telegram |
| rover.due_set | `rover: RoverTask, how: "set"\|"moved"\|"auto", by_name: str\|null, to: [tg], heads: [tg]` | The deadline was set / moved by a head (panel or bot) or put automatically (`by_name: null`, nobody set it within 1 day -> created + `ROVER_AUTO_DUE_DAYS`). `to` = workers (card update + notice), `heads` = production heads (their `h{id}` cards are now stale) |
| rover.remind | `rover: RoverTask, what: "soon"\|"overdue", days_late: int, to: [tg], heads: [tg]` | Celery beat (every minute, from `ROVER_REMIND_HOUR`): `soon` = the deadline is tomorrow (once per date), `overdue` = every day while the job is still `new` after `due_date` (`days_late` >= 1). `heads` is filled only for `overdue` (empty for `soon`) |
| painter.task | `painter: PainterTask (state new), to: [tg]` | The job became active for its molyar (first assignment after the rover was confirmed, or reassignment to a new molyar): the molyar gets the full task card with «✅ Bajardim» (izoh, `POST painters/{id}/done/`). Not emitted (logged) when the molyar has no Telegram; an SMS goes instead (Celery `painter_task_sms`) |
| painter.unassigned | `painter: PainterTask (the new state), prev: UserRef, to: [tg]` | The job moved to another molyar (or lost its type). `to` = the previous molyar: the bot edits **that molyar's stored `t{id}u{uid}` card** to «boshqa molyarga o'tkazildi» without buttons |
| painter.ready | `painter: PainterTask, types: [{id, name, user: UserRef\|null}], to: [tg]` | The rover was confirmed: every active staff holding `oauth.user_production_head` (with Telegram) is asked which team (painter type) gets the job. `types` = all painter types that have a responsible user, ordered by name (example: `event.painter.ready.json`); `painter.type` is the current team if one was picked earlier (legacy). Buttons `POST painters/{id}/type/ {type_id}`. Not emitted (logged) when no head has Telegram. Replaces the old bare «Оповещение о заказе» |
| painter.due_ask | `painter: PainterTask, presets: [5,10,14], to: [tg]` | The job started (first activation): every active staff holding `oauth.user_production_head` (with Telegram) is asked for a deadline - buttons «+5 / +10 / +14 kun» (`POST painters/{id}/due/ {days}`). Not emitted when no head has Telegram |
| painter.due_set | `painter: PainterTask, how: "set"\|"moved"\|"auto", by_name: str\|null, to: [tg], heads: [tg]` | The deadline was set / moved by a head (panel or bot) or put automatically (`by_name: null`, nobody set it within 1 day of `started_at` -> + `PAINTER_AUTO_DUE_DAYS`). `to` = the molyar (card update + notice), `heads` = production heads (their `h{id}` cards are stale) |
| painter.remind | `painter: PainterTask, what: "soon"\|"overdue", days_late: int, to: [tg], heads: [tg]` | Celery beat (every minute, from `PAINTER_REMIND_HOUR`): `soon` = the deadline is tomorrow (molyar only, once per date), `overdue` = every day while the job is still `new` after `due_date` (molyar + heads, `days_late` >= 1). `heads` is empty for `soon`. Jobs still waiting for the rover are skipped |
| painter.done | `painter: PainterTask (state done), by_name: str\|null, to: [tg], heads: [tg], painters: [tg]` | The molyar's work is done (panel or bot). `to` = production heads + assembly managers (deduped): they get a new «Molyar tayyor» message; `heads` = the heads whose `h{id}` card is now stale; `painters` = the assigned molyar (their `t{id}u{uid}` card becomes «done», link only) |
| assembly.ready | `assembly: AssemblyTask, assemblers: [UserRef], to: [tg]` | The order moved to «Сборка»: every active staff holding `oauth.user_production_head` (with Telegram) is asked which assembler gets the job. `assemblers` = active staff holding `oauth.user_assembly`, ordered by name (may be empty - the card then says to pick on the site); `assembly.assembler` is the current pick if made earlier. Buttons `POST assemblies/{id}/assembler/ {user_id}`. Not emitted (logged) when no head has Telegram. Replaces the old bare «Оповещение о заказе» |
| assembly.task | `assembly: AssemblyTask, to: [tg]` | The job became active for its assembler (first pick while in «Сборка», or reassignment): the assembler gets the full task card with «✅ O'rnatildi» (izoh, `POST assemblies/{id}/finish/`). Not emitted (logged) when the assembler has no Telegram; an SMS goes instead (Celery `assembly_task_sms`) |
| assembly.unassigned | `assembly: AssemblyTask (the new state), prev: UserRef, to: [tg]` | The job moved to another assembler (or lost its assembler). `to` = the previous assembler: the bot edits **that user's stored `t{id}u{uid}` card** to «boshqa yig'uvchiga o'tkazildi» without buttons |
| assembly.due_ask | `assembly: AssemblyTask, presets: [5,10,14], to: [tg]` | The job started (first activation): the production heads are asked for a deadline - buttons «+5 / +10 / +14 kun» (`POST assemblies/{id}/due/ {days}`). Not emitted when no head has Telegram |
| assembly.due_set | `assembly: AssemblyTask, how: "set"\|"moved"\|"auto", by_name: str\|null, to: [tg], heads: [tg]` | The deadline was set / moved by a head (panel or bot) or put automatically (`by_name: null`, nobody set it within 1 day of `started_at` -> + `ASSEMBLY_AUTO_DUE_DAYS`). `to` = the assembler, `heads` = production heads (their `h{id}` cards are stale) |
| assembly.remind | `assembly: AssemblyTask, what: "soon"\|"overdue", days_late: int, to: [tg], heads: [tg]` | Celery beat (every minute, from `ASSEMBLY_REMIND_HOUR`): `soon` = the deadline is tomorrow (assembler only, once per date), `overdue` = every day while the job is not finished after `due_date` (assembler + heads, `days_late` >= 1). `heads` is empty for `soon`. Jobs of orders already «Tayyor» are skipped |
| assembly.done | `assembly: AssemblyTask (state checking), by_name: str\|null, to: [tg], heads: [tg], assemblers: [tg]` | The assembler pressed «O'rnatildi» (panel or bot): the job waits for the head's check, the order is **not** «Tayyor» yet. `to` = production heads + assembly managers (deduped): a new «🔧 O'rnatib bo'lishdi» message; chats in `heads` get a «✅ Tayyor» button (`POST assemblies/{id}/confirm/`, stored as `c{id}`), managers (in `to` but not in `heads`) get the plain message; `heads` also = the heads whose `h{id}` card is stale; `assemblers` = the assigned assembler (their `t{id}u{uid}` card becomes «Tekshiruvda - rahbar tasdiqlashi kutilmoqda», no buttons) |
| assembly.confirmed | `assembly: AssemblyTask (state done), by_name: str\|null, to: [tg], heads: [tg], assemblers: [tg]` | The head confirmed (panel or bot): the job is done and the order is «Готов». Same recipient lists as `assembly.done`. The bot edits **all stored `c{id}` cards** (closes other heads' «Tayyor» buttons) to «✅ Tayyor - №N (name tasdiqladi)», the assembler's `t{id}u{uid}` card to done, and sends a short message to `to` chats not in `heads` |
| hr.day_off_set / leave_added / hours_set / off_days_set | `employee, ...` | bot admin commands |

**Rover rules for the bot** (`rover.*`): `rover.rev` is monotonic per rover (every write bumps it: submit, confirm, deadline set/moved/auto) - the bot edits a stored card only when the event's `rev` is not older than the stored one. The bot edits **only cards it stored** for chats listed in the event's `to` / `heads` / `workers`; no stored card = no-op (never send an unsolicited edit). Card keys per chat: checker `{id}` (the `rover.check` card), worker `t{id}` (the `rover.task` card), production head `h{id}` (the `rover.due_ask` card). `rover.check` / `rover.checked` additionally carry `workers` so the worker's `t{id}` card follows the state (`checking` / `done`).

**Painter rules for the bot** (`painter.*`): `painter.rev` is monotonic per job (every write bumps it) - the bot edits a stored card only when the event's `rev` is strictly newer than the stored one. The bot edits **only cards it stored** for chats listed in the event's `to` / `heads` / `painters`; no stored card = no-op. Card keys (store `pnt`): molyar `t{id}u{painter user id}` (one per assignee, so a late `painter.unassigned` of A cannot clobber B's card after A->B->A) production head `h{id}` (the `painter.due_ask` card) and production head `r{id}` (the `painter.ready` team-choice card; edited to «✅ Jamoa: …» when a team is picked, in the bot or on the site, i.e. on `painter.due_ask`; also on `painter.task`, which edits the `r{id}` card to the chosen team). `painter.task` / `painter.unassigned` of one reassignment share a `rev`, which is why the keys are per assignee. Reminders (`painter.remind`) are plain messages, not stored.

**Assembly rules for the bot** (`assembly.*`): `assembly.rev` is monotonic per job (every write bumps it) - the bot edits a stored card only when the event's `rev` is strictly newer than the stored one. The bot edits **only cards it stored** for chats listed in the event's `to` / `heads` / `assemblers`; no stored card = no-op. Card keys (store `asm`): assembler `t{id}u{assembler user id}` (one per assignee, so a late `assembly.unassigned` of A cannot clobber B's card after A->B->A), production head `h{id}` (the `assembly.due_ask` card) and production head `r{id}` (the `assembly.ready` team-pick card; edited to «✅ Jamoa: …» when an assembler is picked, in the bot or on the site, i.e. on `assembly.due_ask` and on `assembly.task`). `assembly.task` / `assembly.unassigned` of one reassignment share a `rev`, which is why the keys are per assignee. Reminders (`assembly.remind`) are plain messages, not stored. The assembler's «✅ O'rnatildi» stays valid while the job is `new` or `assembled` (not `checking`/`done`). The head's confirm card is stored under `c{id}` per head chat; `assembly.confirmed` records its `rev` on `c{id}` so a late `assembly.done` (older `rev`) never sends a fresh «Tayyor» button. The «Yig'ildi» step stays on the site and emits no event.

**Offer rules for the bot** (`offer.*`): `task.rev` is monotonic per (kind, id) (events of one write may share a `rev` - they go to different chats; an answer is always followed by an `offer.changed` with a newer `rev`). The bot ignores an `offer.changed` whose `rev` is not newer than the last it applied for that (kind, id), edits **only the stored cards whose chat id is in `to`** (by role: `work` / `present`), and forgets them after `done` / `answered` / `reassigned` / `cancelled`. `watchers` get a one-line notice, not a card. Files are uploaded on the site only.

**Zamer rules for the bot** (events above): `metering.rev` is monotonic per metering. For `metering.changed` the bot ignores the event when `rev` is not newer than the last one it applied (`met:ver:{id}`), and edits **only the stored messages whose chat id is in `to`** (never anybody else's copy); entries are forgotten after `done` / `cancelled` / `reassigned`. `watchers` get a one-line notice, not a card. Files (photos / video / PDF) are uploaded on the site only; the bot never accepts or sends them.

How events are sent:
- **Async:** `core.bot_notify.emit(event, data)` schedules, via `transaction.on_commit`, `core.tasks.notify_bot.delay(envelope)`. Task: `@shared_task(bind=True, max_retries=8, retry_backoff=True, retry_backoff_max=300)`; retries on connection errors / 5xx, never on 4xx. Envelope `id` is generated in `emit` and stays stable across retries.
- **Sync:** `core.bot_notify.send_event_sync(event, data, timeout=10)` returns the bot's response dict; used only in Celery jobs that need the delivery result (HR `asked += 1` only if delivered, `hr/jobs.py:136`).
- **`can_dm`:** after any `hr.*` delivery the task/job calls `hr.services.record_dm_results(delivered)`.
- **Circuit breaker:** if the bot is unreachable during an HR tick, stop sending for that tick without marking anyone asked; the 90-minute windows retry next tick.


---

# 2. Frozen details (addenda to section 1)

These pin down everything section 1 leaves open. Where they differ from a loose reading of
section 1, this section wins.

## 2.1 Conventions

- Every JSON body is UTF-8. Decimals are strings with two places (rates with four): `"250000.00"`, `"11800.0000"`. Dates are ISO `YYYY-MM-DD`; times are `HH:MM`; datetimes `YYYY-MM-DDTHH:MM:SS` (local Asia/Tashkent, naive).
- Telegram ids are JSON integers. `channel_id` is a string (it can be `@name` or `-100...`); an empty string means "no channel configured - skip the channel post".
- **Recipients are lists of Telegram ids (ints)**: `to`, `admins`, `superusers`, `groups` (group chat ids). The backend computes them, the bot never queries for them. An empty list means nobody gets it.
- Duty events carry `to` (list), `fallback` (bool; true = nobody holds the duty so `to` is the admins) and `fallback_who` (string for the prefix). When `fallback` is true the bot prepends `⚠️ <i>{fallback_who} belgilanmagan (saytda Moliya -> Telegram a'zolar). Xabar sizga keldi:</i>\n\n`.
- Error bodies are always `{"detail": "<Uzbek text>"}`: 400 `ServiceError` (bot shows `❗ {detail}`), 403 role refusal / bad signature, 404, 409 "already done".
- Operations list (`finance/operations/`) is not paginated: the bot paginates `rows`.
- `404` from `finance/orders/{ref}/` etc. means "no such record"; the bot says so.

## 2.2 Extra DTOs

- **ManualOrder** `{ref, client, phone, price, is_closed}`.
- **MonthSummary** `{month, opening, income, expense, closing, count}` (decimals as strings).
- **DaySummary** `{expense, income, balance, given_to_staff, boss_personal, home, transfers, count}`.
- **RankingRow** `{telegram_id, name, pts, disc, bonus, adj, wins}` (`wins` only meaningful for year rankings, else 0).
- **Operation list row** = Operation + `signed_amount` (string) + `internal` (bool, true for transfers / excluded categories as the bot renders them with ↔️).
- **Operation detail** = Operation + `can_delete` + `can_attach` (bool, computed for the actor).
- **OrderCard** admin-only keys (`total, currency, price_uzs, paid, rest`) are *absent* (not null) for non-admin actors; see `dto.order_card_staff.1.json` vs `dto.order_card_admin.1.json`. `ready_days_left` is an int only for `bucket == "yakun"`.
- **Employee**: `work_start` / `work_end` are the personal values (`""` when the general ones apply); `hours_label` is the effective `HH:MM–HH:MM`; `ontime_until` = effective start + GRACE_MIN; `off_days` is the personal list or null; `off_days_effective` the list actually used; `off_label` a human string (`"Yakshanba"`, or `"rahbar belgilaydi"` when none).
- **DayReportData** (`kind: live`) also has `empty` (nobody expected: show the "no employees expected" line) and `rest_count` (people on a day off / leave / holiday). `groups` is filled only when more than one group is watched. **PeriodReportData** rows carry everything the "needs attention" line is computed from (`late`, `late_r`, `absent`, `early_n`, `viol`, `late_min`).
- **DayReportData / PeriodReportData**: see `dto.day_report_data.1.json` (kind `live`), `.2.json` (kind `past`) and `dto.period_report_data.1.json`. `live`: names/times only, never HTML. `empty: true` on past/period means "no data" and the other keys may be absent.

## 2.3 Endpoint details

- `POST whoami/`: header actor must equal `user.id`. Side effect: `touch_member_username`. `hr.is_admin` is true when the actor is a finance admin.
- `POST link/`: **no actor header**; request `{token, telegram_id}`; 200 `{linked: true, user: {id, name}}`, 404 `{detail}` for a bad signature, unknown user or a malformed token. Plain digits (deprecated) are accepted and logged. A `telegram_id` already linked to another user is moved (unique column).
- `GET finance/config/`: `{channel_id, usd_rate, usd_rate_manual, ready_days, version}`; `usd_rate` is the effective rate string, `usd_rate_manual` the FIN_USD_RATE override (`"0.00"` = Central Bank); `version` is a short string for the bot's cache key.
- `GET finance/members/?set=staff|wallets|pending|active&duty=<field>`: `duty` is one of `is_site_entry, is_feedback, is_bonus_receiver, is_deadline_receiver`. Admin-only except `set=wallets` for the transfer picker (everyone active sees wallets of others: name only is needed, the DTO is the same).
- `POST finance/parse/`: quick mode takes the member's current categories and order ids on the server. Quick result `{kind, val, cur, cat, ord, com}`; `val` is a number string. Money mode result `{amount, cur, orig, rate}`; 400 when USD without a rate.
- `POST finance/operations/`: the actor is the author; `member_tg` may be someone else only for admins (a staff actor writing into another wallet gets 403). `actor_admin` is derived from the actor's role, a body field of that name is ignored. Response `{operation, balance}`.
- `DELETE finance/operations/{n}/`: 403 when `can_delete` is false. The bot confirms in its own UI first.
- `POST finance/requests/{n}/give/`: body `{amount_text}`; null/empty = the requested amount. 409 when already answered.
- `POST finance/bonuses/{ref}/collect/`: `{amount_text, full}` -> `{bonus, rest, full, operation, task}` where `rest` is a formatted-by-bot decimal string and `full` says the order closed.
- `POST finance/handover/{n}/accept/` and `/drop/` -> `{operation, client, sum_text, member_balance}`.
- `GET finance/excel/?month=YYYY-MM`: body is the xlsx; `Content-Disposition: attachment; filename="..."`.
- `GET finance/month-report/excel/?month=YYYY-MM&member=<tg>`: one person's month as xlsx (sheets «Hisobot»: totals, by category, by order, salaries; «Amallar»: every operation with the running balance). `member` omitted = the actor; a non-admin asking for someone else gets 403. `month` omitted = `month_report_target(member)`.
- `GET finance/bonuses/{ref}/card.png`: PNG of the payment sheet (`or_temp=1` builds it for an order without a bonus row).
- `POST finance/feedback/{ref}/`: multipart fields `file` (jpeg/png bytes), `file_id`, `caption`.
- `POST warehouse/products/{id}/photos/`: multipart fields `file` (jpeg/png/webp bytes, at most 10 MB, signed as the raw multipart body like any upload) and optional `tg_file_id` (Telegram's file_id of the same picture, saved as the cache). The backend validates by content (not the filename or content type), applies the EXIF orientation, flattens transparency on white and stores a JPEG of at most 1600 px.
- Response shapes the plan left open: `finance/summary/` -> `{month, scope, member, summary: DaySummary + expense_by_category[{code,name,emoji,sum,n}] + income_by_category + salary_by_worker[{name,sum}], member_balance}`; `finance/operations/` -> `{month, scope, rows}`; `finance/months/` -> `{scope, member, series[{month,label,income,expense}]}`; `finance/wallets/` rows -> `{member, balance, last_day (ISO|null), reported, month_spent}`; `finance/orders/closed-manual/` -> OrderBrief list (`ready_date` = closed date); `finance/bonuses/{ref}/collect/` also returns `rest_text` and `sum_text` (ready-made "5 000 000 so'm" strings); `hr/cant-come/` -> `{result, day, employee?}`; `hr/holidays/{day}/decision/` GET -> `{day, name, decided, days}`; `hr/points/` -> `{employee, value, reason}`.
- HR endpoints: dates in requests are ISO. `hr/day-off/` accepts `{employee, date}` where `date` is `bugun|ertaga|dd.mm[.yyyy]|YYYY-MM-DD`.
- `POST hr/group-message/`: `date` is the Telegram unix timestamp; `from` is Telegram's user dict. Actions: `ignored` (nothing to do), `checkin`, `checkout`, `leave_only` (leaving report without a check-in), `format_warning`. `dm.kind` values: `checkin_on_time`, `checkin_late`, `checkout`, `checkout_early`, `leave_without_checkin`, `format_warning`. `react` is an emoji to react with in the group or null; `reply` is set only when `GROUP_ACK == "reply"`.
- `POST hr/private-text/`: `handled=false` means "not an HR answer - let the finance router have it".
- `POST hr/callback/`: `action` values `uni, lr, er, eta, here, cant, rsn, offreq`; `arg` is the callback's last part (`1`/`0` for uni/lr/er, minutes for eta, reason key for rsn). `reply.kind` is one of `uniform_yes, uniform_no, late_reason_ask, early_reason_ask, eta_ok, here_ok, cant_ask, excused_done, reason_other, offreq_sent`; `reply.data` always has `employee`, plus `eta` (`HH:MM`) where relevant. `alert=true` shows `answer` as a popup alert.
- `POST hr/winners/` and `hr/holidays/{day}/decision/` return 409 when already done.

## 2.4 Event payload notes

- Envelope: `{"id": "<uuid4>", "event": "finance.operation_created", "data": {...}}`; one envelope = one rendered notification batch. The `id` is stable across retries (bot dedup key).
- Per-person events (`daily_reminder`, `month_end_reminder`, `month_late`, `hr.ask_eta`, `hr.out_reminder`, `hr.eta_passed`) carry one `member` / `employee`; the DM goes to that person.
- `finance.operation_created.notify_owner`: true when the author is not the wallet owner; `owner_tg` is the owner's id.
- `finance.request_answered.post_to_channel`: false for answers given on the site (owner decision 5).
- `finance.request_created`: after sending, the bot POSTs `finance/requests/{n}/admin-messages/` with `[[chat_id, message_id], ...]`. Later `request_answered` carries those in `request.admin_messages` so the bot edits the admin messages.
- `finance.bonus_done.also_admins`: admins who were not already in `to` (empty when `fallback`).
- `finance.admin_daily.by_member`: `[{name, sum}]` company expenses per wallet owner; `silent` is the staff names who wrote nothing.
- `hr.ask_eta`, `hr.out_reminder`, `hr.eta_passed` are sent through `send_event_sync`: the backend needs `delivered[0].ok` to count `asked`.
- `hr.live_alert.data` by kind: `late` `{group_title, in_time, late_min, link}`; `late_comment` `{late_reason, comment}`; `eta` `{eta}`; `excused` `{reason}`.
- `hr.winner_pick.rows`: the whole ranking (RankingRow); the bot offers buttons `dv:ann:{m|y}:{period}:{telegram_id}` for the first three.
- Texts, phrase pools and keyboards are owned by the bot; the backend sends data only.

## 2.5 `/notify` semantics

See 1.4. The bot answers 200 even when some recipients failed (`delivered[].ok=false`). `blocked: true` means Telegram 403 / "chat not found"; the backend's `record_dm_results` flips `Employee.can_dm` for `hr.*` events. 400 = unknown event or bad data (never retried). 5xx / connection errors are retried by Celery (up to 8 times, exponential backoff).
