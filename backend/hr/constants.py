"""Fixed values of the davomat (attendance) bot — ported from davomat.txt."""

# Settings the admin changes with /dsozla (defaults; stored values live in HrSetting)
DEFAULTS = {
    "WORK_START": "09:00",
    "WORK_END": "18:00",
    "LEAVE_GRACE_MIN": "5",
    "OUT_MIN_GAP": "60",
    "OUT_REMIND_MIN": "60",
    "GRACE_MIN": "15",
    "OFF_DAYS": "",
    "CHECKIN_FROM": "05:00",
    "REMIND_BEFORE_MIN": "30",
    "REPEAT_ASK_MIN": "60",
    "REPORT_TIME": "11:30",
    "MONTH_REPORT_TIME": "21:00",
    "HOLIDAY_ASK_DAYS": "3",
    "CHECKIN_MODE": "video_note",
    "KEYWORDS": "keldim,keldik,ishdaman,joydaman,otchet,boshladim",
    "UNIFORM_CHECK": "1",
    "GROUP_ACK": "reaction",
    "GROUP_REMIND": "1",
    "GROUP_LIST_MISSING": "0",
    "MANAGER_LIVE_ALERTS": "0",
}
LABELS = {
    "WORK_START": "Ish boshlanishi",
    "WORK_END": "Ish tugashi",
    "LEAVE_GRACE_MIN": "Erta ketishga ruxsat (daq)",
    "OUT_MIN_GAP": "Ketish otcheti (kelgandan keyin kamida, daq)",
    "OUT_REMIND_MIN": "Ketish otchetini eslatish (ish tugagach, daq)",
    "GRACE_MIN": "Kechikishga ruxsat (daq)",
    "OFF_DAYS": "Umumiy dam kunlari",
    "CHECKIN_FROM": "Otchet qabul qilish boshlanishi",
    "REMIND_BEFORE_MIN": "Ertalabki eslatma (ish boshidan oldin, daq)",
    "REPEAT_ASK_MIN": "Qayta so'rash (ish boshidan keyin, daq)",
    "REPORT_TIME": "Kunlik hisobot vaqti",
    "MONTH_REPORT_TIME": "Oylik hisobot vaqti (oy oxirgi kuni)",
    "HOLIDAY_ASK_DAYS": "Bayramdan necha kun oldin so'rash",
    "CHECKIN_MODE": "Otchet turi",
    "KEYWORDS": "Kalit so'zlar",
    "UNIFORM_CHECK": "Forma so'rovi",
    "GROUP_ACK": "Guruhda tasdiqlash",
    "GROUP_REMIND": "Ertalabki guruh eslatmasi",
    "GROUP_LIST_MISSING": "Guruhda kelmaganlarni e'lon qilish",
    "MANAGER_LIVE_ALERTS": "Kech kelganda darhol xabar",
}
TIME_KEYS = ["WORK_START", "WORK_END", "CHECKIN_FROM", "REPORT_TIME", "MONTH_REPORT_TIME"]
BOOL_KEYS = ["UNIFORM_CHECK", "GROUP_REMIND", "GROUP_LIST_MISSING", "MANAGER_LIVE_ALERTS"]
CHECKIN_MODES = ["video_note", "media", "keyword", "media_or_keyword", "any"]
ACK_MODES = ["reaction", "reply", "none"]

# Uzbekistan holidays; Hayit dates are approximate — the bot asks the admin anyway.
UZ_HOLIDAYS = [
    ("01-01", "Yangi yil"),
    ("03-08", "Xalqaro xotin-qizlar kuni"),
    ("03-21", "Navro'z bayrami"),
    ("05-09", "Xotira va qadrlash kuni"),
    ("09-01", "Mustaqillik kuni"),
    ("10-01", "O'qituvchi va murabbiylar kuni"),
    ("12-08", "Konstitutsiya kuni"),
    ("2026-03-20", "Ramazon hayiti"),
    ("2026-05-27", "Qurbon hayiti"),
    ("2027-03-10", "Ramazon hayiti"),
    ("2027-05-16", "Qurbon hayiti"),
    ("2028-02-27", "Ramazon hayiti"),
    ("2028-05-05", "Qurbon hayiti"),
]

MAX_ASKS = 4
ETA_GRACE_MIN = 5
WEEKDAYS = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
WD_SHORT = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]
MONTHS = [
    "yanvar",
    "fevral",
    "mart",
    "aprel",
    "may",
    "iyun",
    "iyul",
    "avgust",
    "sentabr",
    "oktabr",
    "noyabr",
    "dekabr",
]

ST_LABEL = {
    "on_time": "✅ Vaqtida",
    "late": "⏰ Kech qoldi",
    "waiting": "⏳ Hali kelmadi",
    "absent": "❌ Kelmadi",
    "excused": "📝 Sababli",
    "leave": "🏖 Ta'tilda",
    "off": "😴 Dam kuni",
    "holiday": "🎉 Bayram",
    "noin": "❔ Kelish qayd etilmagan",
}
ST_PLAIN = {
    "on_time": "Vaqtida",
    "late": "Kech qoldi",
    "waiting": "Hali kelmadi",
    "absent": "Kelmadi",
    "excused": "Sababli kelmadi",
    "leave": "Ta'til",
    "off": "Dam kuni",
    "holiday": "Bayram",
    "noin": "Kelish qayd etilmagan",
}
STATUS_CHOICES = list(ST_PLAIN.items())
REASONS = {
    "sick": "Kasal",
    "family": "Oilaviy sabab",
    "agreed": "Rahbar bilan kelishilgan",
    "transport": "Transport / yo'l muammosi",
}

PTS = {
    "ON_TIME": 10,
    "EARLY_BIRD": 2,
    "LATE_REASON": 0,
    "LATE_NO_REASON": -5,
    "ABSENT": -15,
    "LEFT_OK": 5,
    "LEFT_EARLY_REASON": 0,
    "LEFT_EARLY": -5,
    "NO_OUT": -2,
    "NO_IN": -5,
    "UNIFORM_YES": 2,
    "UNIFORM_NO": -3,
    "MONTH_CLEAN": 20,
}
PTS_HELP = "\n".join(
    [
        "<b>⭐ Ballar tizimi</b>",
        "",
        "✅ Vaqtida keldi: <b>+10</b> (10 daqiqa oldin kelsa yana <b>+2</b>)",
        "⏰ Kech keldi: sababli <b>0</b>, sababsiz <b>−5</b>",
        "❌ Sababsiz kelmadi: <b>−15</b> (sababli bo'lsa 0)",
        "🏁 Ish vaqti tugagach ketdi va otchet tashladi: <b>+5</b>",
        "🚪 Erta ketdi: sababli <b>0</b>, sababsiz <b>−5</b>",
        "📭 Ketish otcheti tashlamadi: <b>−2</b>, kelish otcheti tashlamadi: <b>−5</b>",
        "👕 Formada: <b>+2</b>, formasiz: <b>−3</b>",
        "🏅 Oy davomida birorta ham sababsiz kechikish, kelmaslik yoki erta ketish bo'lmasa: <b>+20</b> bonus",
        "",
        "Rahbar qo'shimcha ball bera oladi (yaxshi ish, mijozdan rahmat va h.k.).",
        "Oy oxirida eng ko'p ball to'plagan xodim — <b>🏆 Oy xodimi</b>, yil oxirida — <b>👑 Yil xodimi</b>.",
    ]
)

TXT = {
    "morning": [
        "Har bir buyuk natija vaqtida boshlangan kichik qadamdan boshlanadi. Bugun ham birinchilardan bo'ling! 💪",
        "Intizom - muvaffaqiyatning yarmi. Vaqtida kelgan xodim - jamoaning tayanchi. 🙌",
        "Yangi kun - yangi imkoniyat! Kayfiyatni ko'tarib, ishga vaqtida yetib keling. ☀️",
        "Vaqtni qadrlagan odamni vaqt ham qadrlaydi. Barakali kun tilaymiz! 🌿",
        "Mijoz birinchi taassurotni ochilish paytida oladi. Keling, bugun ham a'lo kutib olamiz! 🤝",
        "Kichik odatlar katta natija beradi: vaqtida kelish, toza forma, yaxshi kayfiyat. Omad! ✨",
        "Jamoa kuchi har bir a'zosining mas'uliyatida. Bugun ham bir-birimizni kutdirmaylik! 👥",
        "Erta turgan yo'l oladi. Hammaga unumli va barakali kun! 🚀",
    ],
    "uniform": [
        "👕 Formangizni unutmang! Toza va dazmollangan forma - kompaniya yuzi.",
        "👔 Eslatma: bugun ham forma kiyishni unutmang, beyjik ham joyida bo'lsin.",
        "🧥 Chiqishdan oldin tekshiring: forma, beyjik, tartibli ko'rinish. ✅",
    ],
    "bye": [
        "Bugungi mehnatingiz uchun rahmat! Yaxshi dam oling. 🌙",
        "Barakali kun bo'ldi. Ertaga ham kutamiz! 👋",
        "Charchamang! Uyga eson-omon yetib oling. 🏠",
        "Rahmat, bugun ham jamoaga katta hissa qo'shdingiz. 💪",
    ],
    "winner": [
        "Vaqtida kelish, mas'uliyat va namunali mehnat — mana g'alaba siri!",
        "Intizom va fidoyilik har doim o'z mevasini beradi.",
        "Siz butun jamoa uchun namunasiz!",
    ],
    "praise": [
        "Barakalla, vaqtida keldingiz! 👏",
        "Zo'r! Bugun ham intizomli boshladingiz. 💪",
        "Rahmat, vaqtida keldingiz. Unumli kun tilayman! ☀️",
        "Ajoyib! Siz kabi xodimlar bilan jamoa kuchli. 🔥",
    ],
}
