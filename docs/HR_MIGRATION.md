# HR (davomat) — Google Apps Script → ser-mebel.uz

Phase 2 of the move (phase 1, finance: docs/FINANCE_MIGRATION.md). Port of
`davomat.txt` into the `hr` Django app; its tables never mix with finance.

## Architecture

> Updated 2026-10-27 (bot refactor): the Telegram handlers left the backend (`hr/telegram.py`
> and `hr/reports.py` are gone). `bot/` forwards raw facts; the backend decides and returns
> data. Contract: `docs/BOT_CONTRACT.md`.

- **bot -> backend** (signed, `/api/v1/bot/hr/...`, `api/views/bot/hr.py`): work-group
  messages (`group-message/`), joins/leaves, private answers (`private-text/`), buttons
  (`callback/`), `/start`, `/holatim`, `/kelolmayman` and every admin command. The rules
  live in `hr/services.py` (`process_group_report`, `process_private_text`,
  `process_employee_callback`, `employee_start`, `announce_winner`, ...). They return what
  happened and what to say (`action`, `react`, `reply`, `dm`) - never message text.
- **backend -> bot** (events, `hr/events.py` -> `core.bot_notify`): the minute-by-minute
  schedule `hr/jobs.py` (celery beat task `hr.tasks.tick`) and live alerts. Steps that need
  to know the person was reached (ask for an ETA, leaving reminder, "promised time passed")
  use `send_event_sync` and count an ask only on a confirmed delivery; if the bot is down
  the tick stops and releases its once-per-day keys, so the next tick (the windows last
  90+ minutes) tries again. Reports are data (`hr/report_data.py`); the bot formats them.
- `Employee.can_dm` is updated from the bot's delivery results (`record_dm_results` after
  every `hr.*` event, `hr/dm-status/` after interactive DMs).
- Admins = finance admins (`TelegramMember.role == admin`), as in the Apps Script.
- A finished day is **frozen** (`Attendance.finalized`, status + points stored) - what
  the «Davomat» sheet row used to be. Today is computed live.
- The admin's "how many days off?" answer (`AWAIT_<id>` rows in `HrState`) is now the bot's
  Redis FSM state; migration `hr/0002` deletes the dead rows.
- Site: «HR» section (/hr): today board, journal (HR can correct a day; points are
  recomputed), rating + extra points + «Oy/Yil xodimi», employees (hours, days off),
  holidays/leaves, settings and groups, Excel.

## Data map

| Apps Script                     | DB                         |
|---------------------------------|----------------------------|
| «Davomat» sheet rows            | hr.Attendance (finalized)  |
| dv_e_<tg>                       | hr.Employee                |
| dv_groups                       | hr.WorkGroup               |
| dv_s_<KEY>                      | hr.HrSetting               |
| dv_holidays, dv_hd_<day>        | hr.Holiday, hr.HolidayDecision |
| dv_leaves                       | hr.Leave                   |
| dv_adj_<ym>                     | hr.PointAdjustment         |
| dv_win_<m|y>_<period>           | hr.Winner                  |
| dv_a_<day>_<tg> (today)         | hr.Attendance (live)       |
| dv_since, dv_curday             | hr.HrState SINCE / CURDAY  |

ScriptProperties are not in the sheet: `docs/davomat_export.gs` writes them to a
«DavomatExport» sheet once, then `python manage.py import_davomat_sheet` reads both.

## Ishga tushirish tartibi (o'zbekcha)

### Staging (test.ser-mebel.uz, test bot bilan)

1. Apps Script'da yangi fayl ochib `docs/davomat_export.gs` ni joylang va
   `davomatExport` ni ▶ ishga tushiring — jadvalda «DavomatExport» varag'i paydo bo'ladi.
2. Jadvalni .xlsx qilib yuklab oling (moliya importi uchun ham shu fayl).
3. Serverda:
   ```
   docker cp SerMebel.xlsx testback:/tmp/book.xlsx
   docker exec -it testback python manage.py import_davomat_sheet --xlsx /tmp/book.xlsx --dry-run
   docker exec -it testback python manage.py import_davomat_sheet --xlsx /tmp/book.xlsx
   ```
   Oxirida «Yakunlangan kunlar» ✅ bo'lishi kerak; ogohlantirishlarni (o'tkazib yuborilgan
   qatorlar, «Ball» farqlari) o'qib chiqing.
4. test.ser-mebel.uz → HR: jurnal, reyting, xodimlar (ish vaqti, dam kunlari) eski
   jadval bilan bir xilligini tekshiring.
5. Sinov uchun alohida test guruh oching, **test botni** qo'shib admin qiling, guruhda
   `/ulash` yozing va video-doiracha tashlab ko'ring.

### Production (staging'dan keyin) — bir kunda, bo'shliqsiz

1. **Avval** sayt botini har bir ish guruhiga qo'shing va **admin** qiling (admin
   bo'lmasa bot video-doirachalarni ko'rmaydi). Hozircha `/ulash` yozmang — eski bot
   ishlab turibdi, ikki bot bir vaqtda javob bermasin.
2. Ish kuni oxirida (hamma ketish otchetini tashlagach) Apps Script'da davomatni
   to'xtating: menyu «🕘 Davomatni to'xtatish».
3. Darhol `davomatExport` ni ishga tushiring, jadvalni yuklab oling va production'da
   import qiling (`--dry-run` dan keyin). Import kuni — yangi hisobning birinchi kuni:
   undan oldingi ma'lumotsiz kunlar «Kelmadi» bo'lib yozilmaydi.
4. Har guruhda `/ulash` yozing — xodimlarga «🤖 Botga ulanish» tugmasi chiqadi. Ular uni
   bosishi kerak (yangi bot faqat shundan keyin shaxsiy xabar yoza oladi). Kim
   ulanmaganini HR → Xodimlar'da «Bot» ustuni ko'rsatadi.
5. Eski botni guruhlardan chiqaring.

Import qayta ishga tushirilsa faqat **yetishmagan** yozuvlarni qo'shadi: saytda qilingan
tuzatishlar ustidan yozilmaydi. Jadvaldagi «Ball» ustuni ishlatilmaydi — ballar
qoidalar bo'yicha qayta hisoblanadi; farq qilgan kunlar hisobotda ko'rsatiladi.
