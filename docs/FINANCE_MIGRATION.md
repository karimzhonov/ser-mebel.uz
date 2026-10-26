# Moliya (finance) — Google Apps Script → ser-mebel.uz

Phase 1 of moving the SerMebel Telegram finance bot (Google Sheets + Apps Script,
`code.txt`) into the product. Phase 2 (HR / davomat, `davomat.txt`) is NOT part of
this change — davomat keeps running on Apps Script until then, and its data is never
read or written here.

## Architecture

```
Telegram ──webhook──► bot/ (aiogram, BOT_TOKEN from bot/config.py)
                        │  finance router: forwards private messages + callbacks
                        │  POST http://back:8000/api/v1/finance/telegram/update/
                        │  header X-Bot-Signature = HMAC-SHA256(BOT_TOKEN, body)
                        ▼
                    backend/accounting/telegram/   (port of code.txt: router, flows, texts)
                        │  every write goes through accounting/services.py
                        ▼
                    Postgres  ◄── backend/api/views/finance.py ◄── frontend /finance/*
                        ▲
   scheduler (python manage.py finance_scheduler) — hourly/daily jobs of code.txt
```

- **One source of rules**: `accounting/services.py`. The bot handlers and the REST API
  both call it, so a row created in Telegram and one created on the site behave the same
  (balances, transfer pairs, channel posts, bonus checks).
- **The bot stays thin**: it does not get new Tortoise models (no new DB contract).
  It only forwards the raw update; the backend replies through the Telegram Bot API with
  the same `BOT_TOKEN` (already in the `back` service env). `/start <user_id>` (site
  account linking) is not forwarded and works exactly as before.
- **Draft state** (multi-step "Chiqim → summa → kategoriya → …" flows) lives in the DB
  (`accounting.BotSession`), not in aiogram's MemoryStorage — prod runs 4 uvicorn
  workers, so memory state would be lost between steps.
- **Orders come from the site DB** — the Apps Script logged into `/admin/` and scraped
  HTML for statuses, `Итого`, `Полученная сумма`, `Дата сдачи`. Now these are read
  straight from `order.Order` (`price`, `discount`, `lost_money`, `status`, `end_date`).
  Order ids in operations are the site's `order_number`; ids that never existed on the
  site (`SM-001`, manual ones) are kept as `order_ref` text + `accounting.ManualOrder`.

## Telegram roles (separate from site permissions)

`oauth.TelegramMember` — one row per Telegram account using the finance bot, optionally
linked to a site `oauth.User`. It does NOT add columns to `oauth_user`, so the bot's
hand-mirrored `bot/db/models/oauth.py` is unaffected.

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

1. `test` branchni push qiling — deploy o'zi `scheduler` konteynerini ham ko'taradi.
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
   tasdiqlash shart emas. Yangi xodimlar esa /moliya yozib ro'yxatdan o'tadi (oddiy /start
   saytning odatdagi salomini ko'rsatadi, sayt foydalanuvchilarini chalg'itmaslik uchun).

Google API orqali (yuklab olmasdan): Google Cloud'da service account yarating, jadvalni
uning e-mailiga «Ko'ruvchi» qilib ulashing va:
`python manage.py import_finance_sheet --sheet-id <ID> --credentials /tmp/sa.json`

### Nima o'zgardi (foydalanuvchi uchun)

- Bot tugmalari va buyruqlari o'sha-o'sha. Farqi: buyurtmalar endi saytdan to'g'ridan-to'g'ri
  olinadi (soatlik «saytdan yangilash» kerak emas), «➕ Yangi buyurtma» faqat saytda yo'q
  ID lar uchun.
- Birinchi /start yozgan odam endi avtomatik rahbar bo'lmaydi — rahbarni saytda belgilaysiz.
- Telegram a'zo sayt profiliga avtomatik ulanmaydi (botdagi `/start <id>` bog'lanishi
  tekshirilmagan) — Moliya → Sozlamalar → Telegram a'zolar'da qo'lda ulang.
- Saytda xodim (barcha hamyonlarni ko'rish huquqi yo'q) faqat o'zi kiritgan, oxirgi 2 kundagi
  yozuvni o'zgartira/o'chira oladi; «Rahbardan» va o'tkazmani faqat rahbar yozadi — botdagi
  qoidalar bilan bir xil.
- Hisob-kitob varaqasi rasmi Google Slides o'rniga serverda chiziladi; o'z foningizni
  botga `/shablon` deb yuborsangiz bo'ladi (`/shablon oddiy` — standart dizayn).
