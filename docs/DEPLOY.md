# Deploy: React panel + API (prod / staging)

Yangi arxitektura: sayt uchun yagona kirish nuqtasi — `front` konteyneri (nginx).

```
Internet ──TLS──> server nginx ──> front (:3000) ──┬─ /            React SPA
                                                    ├─ /media /static  diskdan (./media, ./static)
                                                    └─ /api /admin /filer ──> back (:8000)
          server nginx ──> bot (:7000)   (Telegram webhook — avvalgidek)
```

`back` 8000-portda ochiq qoladi — orqaga qaytish (rollback) uchun.

---

## 1. Bir martalik sozlash (birinchi deploydan oldin)

### 1.1 Docker Hub
CI yangi image'ni push qiladi: `khtkarimzhonov/front.ser-mebel.uz`.
- Hub odatda repo'ni birinchi push'da o'zi yaratadi. Agar akkauntda bu o'chirilgan bo'lsa, repo'ni qo'lda yarating (`api.` va `bot.` repo'lari bilan bir xil ko'rinishda).

### 1.2 GitHub → Settings → Environments
| Environment | O'zgaruvchi | Qiymat |
|---|---|---|
| `test` | `FRONT_PORT` (Variables) | `3001` (yoki boshqa bo'sh port; prod'nikidan farqli bo'lsin) |
| `production` | `FRONT_PORT` | **qo'ymang** → `3000` ishlatiladi |

Qolgan o'zgaruvchilar o'zgarmaydi. Ixtiyoriy env'lar (`JWT_ACCESS_MINUTES`, `JWT_REFRESH_DAYS`, `API_LOGIN_RATE`, `CORS_ALLOWED_ORIGINS`) hozircha kerak emas — standart qiymatlar yetarli. Ular CI orqali uzatilmaydi.

> **`TELEGRAM_WEBAPP_LOGIN_ENABLED` ni yoqmang.** Bot `/start` orqali Telegram'ni istalgan akkauntga tekshiruvsiz bog'laydi; bu tuzatilmaguncha Telegram orqali avtomatik kirish o'chiq turishi shart.

### 1.3 Serverda portni tekshiring
```bash
ss -ltnp | grep -E ':3000|:3001'   # bo'sh bo'lishi kerak
```

### 1.4 Server nginx konfiguratsiyasi
Fayl odatda `/etc/nginx/sites-available/ser-mebel.uz` (staging uchun — `test.ser-mebel.uz`). O'zgartirishdan oldin nusxa oling:
```bash
cp /etc/nginx/sites-available/ser-mebel.uz /root/ser-mebel.uz.nginx.bak
```

`server { ... }` blokida:
1. Bot webhook'iga tegishli `location` (7000-portga yo'naltiradigan) — **o'zgarishsiz qoldiring**.
2. Hozir `127.0.0.1:8000` ga yo'naltiradigan `location /` ni, `/media/` va `/static/` uchun `alias` bloklarini **olib tashlang** va o'rniga quyidagini qo'ying:

```nginx
    client_max_body_size 200m;

    location / {
        proxy_pass http://127.0.0.1:3000;      # staging'da: FRONT_PORT (masalan 3001)
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        # $remote_addr bilan ALMASHTIRAMIZ (qo'shmaymiz) — mijoz soxta IP yubora olmaydi.
        proxy_set_header X-Forwarded-For   $remote_addr;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_read_timeout 120s;
    }
```
`listen 443 ssl` va certbot qatorlari o'zgarmaydi.

> Agar `/media/` ni server nginx'ning o'zi berishini xohlasangiz (alias bilan), u blokka albatta quyidagini qo'shing — aks holda yuklangan `.html/.svg` fayl panel tokenlarini o'g'irlashi mumkin:
> ```nginx
> add_header Content-Security-Policy "default-src 'none'; script-src 'none'; object-src 'self'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'" always;
> add_header X-Content-Type-Options nosniff always;
> ```

Tekshirish va qo'llash — **buni deploydan keyin, `front` konteyneri ishga tushgach** qiling (2-bo'lim):
```bash
nginx -t && systemctl reload nginx
```

---

## 2. Deploy tartibi

1. **Staging:** `feature/drf-api-react-frontend` → `test` branch'ga merge/push. CI 3 ta image yig'adi va `/var/www/test.ser-mebel.uz` ga deploy qiladi.
   - `back` ishga tushganda `migrate` avtomatik bajariladi (`prodserver.sh`) — yangi `token_blacklist` jadvallari shu yerda yaratiladi.
2. Serverda tekshiring:
   ```bash
   cd /var/www/test.ser-mebel.uz
   docker compose -f docker-compose.prod.yml ps          # back, front, bot, db — "running"
   curl -sI http://127.0.0.1:3001/ | head -1             # 200
   curl -s  http://127.0.0.1:3001/api/v1/meta/ | head -c 80   # {"detail":...} — 401, demak API ishlayapti
   ```
3. Staging nginx'ni 1.4 bo'yicha o'zgartiring → `nginx -t && systemctl reload nginx`.
4. Brauzerda tekshiruv ro'yxati (3-bo'lim).
5. Hammasi joyida bo'lsa → `master` ga merge → prod deploy → prod nginx'ni 1.4 bo'yicha o'zgartiring.

## 3. Deploydan keyingi tekshiruv

- [ ] `https://<domen>/` — kirish sahifasi chiqadi, telefon + parol bilan kirish ishlaydi.
- [ ] `https://<domen>/admin/` — eski admin ochiladi, saqlashda **CSRF xatosi yo'q** (bo'lsa — server nginx'da `X-Forwarded-Proto` yo'q).
- [ ] Rasm/fayllar ko'rinadi (`/media/...`), admin stillari yuklanadi (`/static/...`).
- [ ] Panelda fayl yuklash ishlaydi (замер → «Файлы» → «Загрузить»).
- [ ] Bot xabaridagi «Открыть» tugmasi ishlaydi (hozircha admin sahifasiga olib boradi).
- [ ] Swagger: `https://<domen>/api/docs/` — faqat admin'ga kirgan xodimga ochiladi.

## 4. Xodimlar uchun muhim
- Panelga **telefon + parol** bilan kiriladi. Faqat Telegram orqali (`?telegram_id=`) kirib yurgan xodimlarda parol bo'lmasligi mumkin — superuser ularga parol o'rnatsin: panel → «Сотрудники» → ✏️ → «Новый пароль» (yoki `/admin/`).
- Faqat `is_staff` belgisi bor foydalanuvchilar kira oladi (admin'dagi kabi).

## 5. Rollback
`back` hali ham 8000-portda ochiq. Muammo bo'lsa server nginx nusxasini qaytaring:
```bash
cp /root/ser-mebel.uz.nginx.bak /etc/nginx/sites-available/ser-mebel.uz
nginx -t && systemctl reload nginx
```
Sayt avvalgidek admin orqali ishlaydi; API/front konteynerlari zarar yetkazmaydi.

## 6. Muntazam xizmat (ixtiyoriy, tavsiya)
Muddati o'tgan JWT yozuvlarini haftada bir tozalash (cron):
```bash
0 4 * * 0  docker exec back python manage.py flushexpiredtokens
```

## 7. Eslatmalar
- `deploy.sh` eskirgan (`docker-compose` v1, `:latest` teglari) — undan foydalanmang, deploy faqat GitHub Actions orqali.
- `core/settings.py` da `DEBUG = True` qattiq yozilgan (env'dagi `DEBUG` hisobga olinmaydi) — xatolarda traceback ochiq ko'rinadi. Alohida vazifa sifatida tuzatish tavsiya etiladi.
- `back` konteyneriga `SMS_*` va `ADMIN_BASE_URL` env'lari prod compose orqali uzatilmaydi (avvaldan shunday) — SMS yuborish kerak bo'lsa, ularni qo'shish kerak.
