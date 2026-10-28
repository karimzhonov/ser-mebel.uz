# Moliya (finance) — Google Apps Script → ser-mebel.uz

Phase 1 of moving the SerMebel Telegram finance bot (Google Sheets + Apps Script,
`code.txt`) into the product. Phase 2 (HR / davomat, `davomat.txt`) is NOT part of
this change — davomat keeps running on Apps Script until then, and its data is never
read or written here.

## Architecture

> Updated 2026-10-27 (bot refactor): the Telegram logic left the backend. `bot/` owns every
> button, text and flow; the backend owns data and rules and talks to the bot only through
> the signed internal API and events described in `docs/BOT_CONTRACT.md`.

```
Telegram ──webhook──► bot/ (aiogram + Redis FSM; renders every message)
                        │  signed HTTP (HMAC-SHA256 keyed with BOT_TOKEN)
                        │  POST/GET http://back:8000/api/v1/bot/finance/...   (api/views/bot/finance.py)
                        ▼
                    backend: api/views/bot/* ─► accounting/services.py (rules) ─► Postgres
                        │                                   ▲
                        │ accounting/events.py              │  backend/api/views/finance.py ◄── frontend /finance/*
                        ▼ core.bot_notify.emit (on_commit)
                    Celery  core.tasks.notify_bot (8 retries) ─► POST http://bot:80/notify ─► bot renders + sends
                        ▲
   celery-worker + celery-beat (accounting/tasks.py, schedule in accounting/schedule.py) - hourly/daily jobs; they only emit events
```

- **One source of rules**: `accounting/services.py`. The bot (through `/api/v1/bot/`) and the
  site REST API both call it, so a row created in Telegram and one created on the site
  behave the same (balances, transfer pairs, channel posts, bonus checks). Role rules
  (who may book into whose wallet, admin-only categories, delete window, receiver/duty
  checks, contract money only for admins) are enforced by the backend; the bot only relays
  the signed Telegram id of the acting user.
- **The backend sends nothing to Telegram.** Channel posts, "money was given to you", the
  hourly/daily reminders and the Готов card are *events* (`accounting/events.py`,
  `accounting/followup.py`, `accounting/jobs.py`): data + recipients, no wording. The bot
  renders them. A booking is never undone by a down bot: `emit` runs after commit and the
  Celery task retries with backoff.
- **Draft state** (multi-step "Chiqim -> summa -> kategoriya -> ..." flows) lives in the bot's
  Redis FSM, not in the DB (`accounting.BotSession` and `ProcessedUpdate` were dropped,
  migration `0016`). Update de-duplication is the bot's Redis key; there is no outbox any more
  (a crash mid-update is recovered by Telegram's own retry).
- **Orders come from the site DB** - the Apps Script logged into `/admin/` and scraped
  HTML for statuses, `Итого`, `Полученная сумма`, `Дата сдачи`. Now these are read
  straight from `order.Order` (`price`, `discount`, `lost_money`, `status`, `end_date`).
  Order ids in operations are the site's `order_number`; ids that never existed on the
  site (`SM-001`, manual ones) are kept as `order_ref` text + `accounting.ManualOrder`.
- **Files**: receipts/screenshots are Telegram `file_id`s. The site's receipt view fetches the
  bytes from the bot (`GET /files/{file_id}`, `core.bot_notify.fetch_file`); the bot uploads
  feedback screenshots / the report background to the backend (multipart).
- **Charts** (donut, bars) are drawn by the bot (QuickChart). Only the payment sheet
  (`accounting/images.py report_card_png`) and the Excel export stay in the backend.

## Telegram roles (separate from site permissions)

`oauth.TelegramMember` — one row per Telegram account using the finance bot, optionally
linked to a site `oauth.User`. It does NOT add columns to `oauth_user`. (The bot no longer
mirrors any table: it has no database connection.)

| Apps Script                         | TelegramMember                          |
|-------------------------------------|-----------------------------------------|
| Xodimlar.Rol = admin/xodim/pending/blocked | `role` = admin / staff / pending / blocked |
| SAYT_KIRITUVCHI (/saytchi)          | `is_site_entry`                         |
| FIKR_XODIM (/fikrchi)               | `is_feedback`                           |
| BONUS_XODIM / name "Yusupov" (Umid) | `is_bonus_receiver`                     |
| SROK_XODIM / name "Gafurov" (Islom) | `is_deadline_receiver`                  |

"Task-only" members (site entry / feedback, not admin) get the task keyboard and no
wallet, as before.

## Data map (Google Sheets → DB)

| Sheet             | Model                         | Key (idempotent re-import)     |
|-------------------|-------------------------------|--------------------------------|
| Xodimlar          | oauth.TelegramMember          | Telegram ID                    |
| Ishchilar         | accounting.Worker             | (group, name)                  |
| Amallar           | accounting.Operation          | ID → `number`                  |
| Buyurtmalar       | accounting.ManualOrder (only ids not on the site) | ID     |
| Oylik hisob       | accounting.MonthReport        | (Xodim ID, Oy)                 |
| Bonuslar          | accounting.OrderBonus         | Buyurtma ID                    |
| Kafolat xatlari   | accounting.WarrantyLetter     | Buyurtma ID                    |
| Saytga kiritish   | accounting.SiteEntryTask      | Kod                            |
| Mijoz fikrlari    | accounting.ClientFeedback     | Buyurtma ID                    |
| Sozlamalar        | constance FIN_* keys          | Kalit                          |
| Davomat, Xulosa, Tekshiruv | — not imported (HR phase 2 / computed views) |      |

Import: `python manage.py import_finance_sheet --xlsx export.xlsx` or
`--sheet-id <id> --credentials service-account.json`. `--dry-run` prints what would
change; every run ends with a check that each wallet balance and the operation totals
equal the sheet's own numbers.

## Cutover (owner)

1. Revoke the old finance bot token in @BotFather (it was committed to a public repo).
2. Deploy `test` → check on test.ser-mebel.uz with the staging (test) bot.
3. Final import on production, then in Apps Script: delete the `hourly` trigger and make
   `route_` call only `DV.handle(up)` — davomat keeps working, finance stops answering
   there. Finance staff press /start in the site bot; their roles are already imported.

## Ishga tushirish tartibi (o'zbekcha)

### 1. Staging (test.ser-mebel.uz)

1. `test` branchni push qiling — deploy o'zi `redis`, `celery-worker`, `celery-beat` konteynerlarini ham ko'taradi.
   Yangi secret kerak emas (`BOT_TOKEN` back va bot'da allaqachon bor).
2. Google jadvalni yuklab oling: Fayl → Yuklab olish → Microsoft Excel (.xlsx).
3. Serverga nusxalang va importni avval sinab ko'ring (hech narsa saqlanmaydi):
   ```
   docker cp SerMebel.xlsx testback:/tmp/book.xlsx        # konteyner nomi: STACK_PREFIX + back
   docker exec -it testback python manage.py import_finance_sheet --xlsx /tmp/book.xlsx --dry-run
   ```
   Oxirida «Tekshiruv (jadval = baza)» bo'limida hamma qator ✅ bo'lishi kerak.
4. Haqiqiy import: shu buyruq `--dry-run`siz.
5. test.ser-mebel.uz → Moliya → Sozlamalar → «Telegram a'zolar»: rollar va vazifalar
   (bonus oluvchi, srok, saytga kirituvchi, mijoz fikri) to'g'ri chiqqanini tekshiring.
   O'zingizning sayt profilingizni «Rahbar» a'zoga ulang («Sayt profili»).
6. Test botga /start yozing → «💳 Hamyonim», «➖ Chiqim», «📊 Ma'lumot» va hokazo.

### 2. Production (ser-mebel.uz) — staging'dan keyin

1. Apps Script'da moliyani to'xtating (Davomat ishlashda davom etadi):
   - Triggers bo'limida `hourly` triggerni o'chiring (`davomatTick` qoladi).
   - `route_` funksiyasining boshini shunday qiling:
     ```js
     function route_(up) {
       if (typeof DV !== 'undefined' && DV.handle(up)) return;
       return; // Moliya endi ser-mebel.uz botida
     }
     ```
   - Joylashtirish → Yangi versiya.
2. Jadvalni qayta .xlsx qilib yuklab oling (oxirgi yozuvlar bilan) va production'da import
   qiling (avval `--dry-run`). Qayta import xavfsiz — yozuvlar ikki marta qo'shilmaydi.
3. Xodimlarga: «endi @<sayt boti> ga /start yozing» — rollari import qilingan, qayta
   tasdiqlash shart emas. Yangi xodimlar /start yozib ro'yxatdan o'tadi (/moliya ham ishlaydi).
   Ro'yxatda yo'q odamning oddiy matniga bot javob bermaydi.

Google API orqali (yuklab olmasdan): Google Cloud'da service account yarating, jadvalni
uning e-mailiga «Ko'ruvchi» qilib ulashing va:
`python manage.py import_finance_sheet --sheet-id <ID> --credentials /tmp/sa.json`

### Nima o'zgardi (foydalanuvchi uchun)

- Bot tugmalari va buyruqlari o'sha-o'sha. Farqi: buyurtmalar endi saytdan to'g'ridan-to'g'ri
  olinadi (soatlik «saytdan yangilash» kerak emas), «➕ Yangi buyurtma» faqat saytda yo'q
  ID lar uchun.
- Birinchi /start yozgan odam endi avtomatik rahbar bo'lmaydi — rahbarni saytda belgilaysiz.
- Telegram a'zo sayt profiliga avtomatik ulanmaydi — Moliya → Sozlamalar → Telegram a'zolar'da
  qo'lda ulang. (Sayt profili <-> Telegram bog'lanishi endi imzolangan havola bilan ishlaydi:
  `?start=u<id>_<imzo>`; eski raqamli havola bir reliz davomida qabul qilinadi.)
- Saytda xodim (barcha hamyonlarni ko'rish huquqi yo'q) faqat o'zi kiritgan, oxirgi 2 kundagi
  yozuvni o'zgartira/o'chira oladi; «Rahbardan» va o'tkazmani faqat rahbar yozadi — botdagi
  qoidalar bilan bir xil.
- Hisob-kitob varaqasi rasmi Google Slides o'rniga serverda chiziladi; o'z foningizni
  botga `/shablon` deb yuborsangiz bo'ladi (`/shablon oddiy` — standart dizayn).
