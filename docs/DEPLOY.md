# Deploy: React panel + API (prod / staging)

**Serverda hech narsa sozlanmaydi.** Server nginx'i avvalgidek domenni `127.0.0.1:8000`
ga (staging'da — `BACK_PORT` ga) yuboradi. Faqat endi bu portni `front` konteyneri
egallaydi va so'rovlarni o'zi taqsimlaydi:

```
Internet ──TLS──> server nginx (o'zgarishsiz) ──> :8000 = front (nginx)
                                                    ├─ /                  React panel
                                                    ├─ /?telegram_id=…    ─┐
                                                    ├─ /api /admin /filer ─┴─> back (ichki tarmoq, port ochilmagan)
                                                    └─ /media /static     diskdan (./media, ./static)
          server nginx ──> :7000 = bot (o'zgarishsiz)
```

## Deploy

Hech qanday qo'shimcha sozlash kerak emas — GitHub o'zgaruvchilari ham, server nginx ham o'zgarmaydi.

1. `test` branchni push qilish → CI 3 ta image yig'adi (api, **front**, bot) va staging'ga deploy qiladi.
   `back` ishga tushganda `migrate` avtomatik bajariladi (`prodserver.sh`).
2. Staging'da tekshiruv ro'yxati (pastda).
3. Hammasi joyida bo'lsa → `master` ga merge → prod deploy.

Docker Hub `khtkarimzhonov/front.ser-mebel.uz` repo'sini birinchi push'da odatda o'zi yaratadi.
Agar CI "repository does not exist" deb yiqilsa — Hub'da shu nomli repo'ni qo'lda yarating.

## Tekshiruv ro'yxati

- [ ] `https://<domen>/` — yangi panelning kirish sahifasi, telefon + parol bilan kirish ishlaydi.
- [ ] `https://<domen>/admin/` — eski admin ochiladi, saqlashda CSRF xatosi yo'q.
- [ ] Rasmlar (`/media/…`) va admin stillari (`/static/…`) yuklanadi.
- [ ] Panelda fayl yuklash ishlaydi (замер → «Файлы» → «Загрузить»).
- [ ] Bot xabaridagi «Открыть» tugmasi ochiladi (admin sahifasiga olib boradi).
- [ ] Serverda: `docker compose -f docker-compose.prod.yml ps` — `back`, `front`, `bot`, `db` ishlayapti.

## Xodimlar uchun
- Panelga **telefon + parol** bilan kiriladi. Faqat Telegram orqali kirib yurgan xodimlarda
  parol bo'lmasligi mumkin — superuser ularga parol o'rnatsin: panel → «Сотрудники» → ✏️.
- `TELEGRAM_WEBAPP_LOGIN_ENABLED` ni yoqmang: botdagi `/start` bog'lash tekshiruvsiz.

## Rollback
Oldingi commit'ni `test`/`master` ga qaytarib push qiling — CI eski compose bilan qayta
deploy qiladi (`back` yana 8000-portni oladi). Serverda qo'lda ish yo'q.

## Ixtiyoriy
- Haftalik cron: `docker exec back python manage.py flushexpiredtokens` (muddati o'tgan JWT yozuvlari).
- Agar server nginx `/media/` ni o'zi `alias` bilan bersa, yuklangan fayllar uchun xavfsizlik
  sarlavhalari (`frontend/nginx.conf` dagi `Content-Security-Policy` va `nosniff`) u yerda ishlamaydi —
  shunda o'sha blokka ham qo'shish tavsiya etiladi. `/media/` ni 8000-portga proksi qilsa, hech narsa kerak emas.

## Eslatmalar
- `deploy.sh` eskirgan — deploy faqat GitHub Actions orqali.
- `core/settings.py` da `DEBUG = True` qattiq yozilgan (avvaldan) — alohida tuzatish kerak.
- `back` ga `SMS_*`, `ADMIN_BASE_URL` env'lari prod compose orqali uzatilmaydi (avvaldan shunday).
