# Bot <-> backend contract (frozen, Phase 0)

The Telegram bot (`bot/`) holds no business rules and no database connection. The backend
(`backend/`) owns data and rules (`<app>/services.py`) and exposes a signed internal API
under `/api/v1/bot/...`. The backend tells the bot what to send through Celery
(`core.tasks.notify_bot`) which calls the bot's `POST /notify`.

Reference implementation: `backend/core/bot_signing.py` (signing), `backend/core/bot_notify.py`
(`emit`, `send_event_sync`, `fetch_file`), `backend/api/views/bot/*` (endpoints),
`backend/accounting/events.py` and `backend/hr/events.py` (event payload builders).

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
(`u\d+_[0-9a-f]{10}`, or plain digits for one more release) to `POST link/`; only the backend
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

- **Member** `{id, telegram_id, name, username, role, is_admin, is_active_member, is_task_only, has_wallet, is_site_entry, is_feedback, is_bonus_receiver, is_deadline_receiver, site_user: str|null}`
- **Category** `{code, name, emoji, kind, admin_only, no_order, archive, excluded}`
- **Operation** `{number, date, time, kind, amount, currency, orig_amount, rate, category: Category, member: {telegram_id, name}, author_tg, order_ref, comment, worker, pay_type, receipt_file_id, is_deleted, handover}`
- **OrderBrief** `{ref, client, bucket, ready_date}`
- **OrderCard** `{ref, client, phone, bucket, status_label, ready_date, end_date, ready_days_left, manual: {is_closed, price}|null, stats: {spent, collected, cats: [{code, name, emoji, sum}], last_ops: [Operation]}}`; adds `total, currency, price_uzs, paid, rest` **only for finance admins** (server-side; replaces `full = ctx.admin`, `router.py:1309`).
- **Bonus** `{order_ref, client, description, total, currency, ready_date, status, rest, days, percent, bonus, note, got_text}`
- **MoneyState** `{paid, rest, src}`
- **MoneyRequest** `{number, member: Member, amount, currency, orig_amount, reason, status, answer, created_at, admin_messages: [[chat_id, message_id]], member_balance}`
- **Worker** `{id, name, group, position}` · **Car** `{id, name}`
- **SiteEntryTask** `{code, order_ref, client, sum_text, rest_text, taken_by, date, is_done}`
- **Feedback** `{order_ref, client, phone, status, ready_date, asked_date}` · **Warranty** `{order_ref, client, given}`
- **Employee** `{telegram_id, number, name, username, is_active, can_dm, group: {chat_id, title}|null, work_start, work_end, hours_label, ontime_until, off_days, off_days_effective, off_label}`
- **WorkGroup** `{chat_id, title, is_active}`

### 1.3 Backend endpoints (`/api/v1/bot/`), all signed

Actor comes from `X-Bot-Actor`. Every role rule is enforced server-side.

**Common**

| Method | Path | Request | Response | Notes |
|---|---|---|---|---|
| POST | `whoami/` | `{user: {id, username, first_name, last_name}}` | `{finance_member: Member\|null, hr: {employee: Employee\|null, is_admin: bool}}` | Side effect: new `accounting.services.touch_member_username(tg, username)` (replaces `_sync_profile`, `router.py:357`) |
| POST | `link/` | `{token, telegram_id}` | `{linked, user}` / 404 | `oauth.services.link_telegram` (verifies signed token; Owner decisions #1) |

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
| GET | `finance/handover/` (admin) | `[Operation]` | `S.handover_pending` |
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
| POST | `finance/operations/` | `{member_tg, kind, amount, category, currency, orig_amount, rate, order_ref, comment, receipt_file_id, worker, pay_type}` → `{operation, balance}`; `actor_admin` derived server-side | `S.create_operation`, then `followup.bonus_check(ref, ok_hour=False)` for client payments | `operation_created` |
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
| POST | `finance/bonuses/{ref}/collect/` (receiver) | `{amount_text, full}` → `{bonus, rest, full, operation, task}` | `S.bonus_collect` + `S.site_entry_create` | `site_entry_created`, `handover_requested` (actor not admin), `bonus_done` (if full) |
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
- `POST /webhook` and `POST /user/{chat_id}/message`: unchanged.

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
| finance.month_submitted | `member, month, summary, note, closing, admins, channel_id` | bot |
| finance.manual_order_created / manual_order_closed | `order, spent, channel_id` | bot |
| finance.handover_requested | `operation, who, ref, client, sum_text, rest_text, admins` | bot collect |
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
| finance.deadline | `order{ref, client, end_date, status_label, phone, address}, left_days, key, to, fallback` | `followup.deadline_reminders` |
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
| hr.live_alert | `admins, kind: late\|late_comment\|eta\|excused, employee, data` | group-message, private-text, callback |
| hr.off_request / off_request_answered | `admins\|employee, day, approve` | callback / admin |
| hr.employee_left / bot_added_to_group | `admins, name\|title` | membership |
| hr.points_added | `employee, value, reason, from_site` | bot `/ball`; site `PointAdjustmentViewSet.perform_create` (`hr.py:204`) |
| hr.winner_announced | `kind, period, employee, pts, disc, groups` | bot `ann`; site `WinnerViewSet.announce` (`hr.py:245`) |
| hr.holiday_applied | `hol_day, name, n, days, admins, groups` | bot |
| hr.day_off_set / leave_added / hours_set / off_days_set | `employee, ...` | bot admin commands |

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
- `GET finance/bonuses/{ref}/card.png`: PNG of the payment sheet (`or_temp=1` builds it for an order without a bonus row).
- `POST finance/feedback/{ref}/`: multipart fields `file` (jpeg/png bytes), `file_id`, `caption`.
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
