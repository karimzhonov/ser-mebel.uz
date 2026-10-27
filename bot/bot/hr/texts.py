"""Fixed phrases and labels of the davomat bot (copied from the old backend/hr/constants.py
and backend/hr/telegram.py: the bot has no Python import of Django code)."""

from __future__ import annotations

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
REASONS = {
    "sick": "Kasal",
    "family": "Oilaviy sabab",
    "agreed": "Rahbar bilan kelishilgan",
    "transport": "Transport / yo'l muammosi",
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


# ------------------------------------------------------------------ commands, menus
EMP_CMDS = ["holatim", "kelolmayman", "ballarim", "ballar"]
ADMIN_CMDS = [
    "davomat",
    "dhisobot",
    "dkecha",
    "dhafta",
    "doy",
    "djadval",
    "dxodimlar",
    "damkun",
    "dam",
    "tatil",
    "tatillar",
    "tatil_ochir",
    "bayram",
    "bayramlar",
    "bayram_ochir",
    "dchiqar",
    "dqayta",
    "dsozlamalar",
    "vaqt",
    "kechikish",
    "dsozla",
    "guruhlar",
    "dyordam",
    "ishvaqti",
    "ball",
    "reyting",
    "dtozala",
]
MENU_BTN = "🕘 Davomat"
IV_TITLE = "🕐 Kimning ish vaqtini belgilaymiz?\n(qavsda hozirgi vaqti)"
IV_PRESETS = [("09:00", "18:00"), ("09:00", "19:00"), ("10:00", "19:00")]


# Setting keys the admin may change with /dsozla (the backend validates again).
SETTING_KEYS = frozenset(
    [
        "WORK_START", "WORK_END", "LEAVE_GRACE_MIN", "OUT_MIN_GAP", "OUT_REMIND_MIN",
        "GRACE_MIN", "OFF_DAYS", "CHECKIN_FROM", "REMIND_BEFORE_MIN", "REPEAT_ASK_MIN",
        "REPORT_TIME", "MONTH_REPORT_TIME", "HOLIDAY_ASK_DAYS", "CHECKIN_MODE", "KEYWORDS",
        "UNIFORM_CHECK", "GROUP_ACK", "GROUP_REMIND", "GROUP_LIST_MISSING",
        "MANAGER_LIVE_ALERTS",
    ]
)  # fmt: skip

# Reply-keyboard buttons of the finance menu: a tap on one of them is never an answer to
# an HR question (old hr/telegram.py: MENU_STAFF + MENU_ADMIN + "Vazifalarim"). Keep in
# sync with the finance menu; finance code may add more with register_menu_buttons().
FINANCE_MENU_BUTTONS: set[str] = {
    "➖ Chiqim",
    "➕ Kirim",
    "💳 Hamyonim",
    "📋 Operatsiyalar",
    "🧾 Buyurtmalar",
    "📤 Oylik hisob",
    "🙏 Rahbardan pul so'rash",
    "🔄 Xodimga pul berish",
    "❓ Yordam",
    "📊 Ma'lumot",
    "💸 Pul berish",
    "👛 Hamyonlar",
    "🔍 Tekshiruv",
    "📥 Excel",
    "📋 Vazifalarim",
}


def register_menu_buttons(*texts: str) -> None:
    FINANCE_MENU_BUTTONS.update(texts)


# ------------------------------------------------------------------ admin help
ADMIN_HELP = "\n".join(
    [
        "<b>🕘 Davomat — rahbar buyruqlari</b>",
        "",
        "Hisobot har kuni 11:30 da, oylik hisobot oy oxirida o'zi keladi. Hammasi saytda ham: HR bo'limi.",
        "",
        "/davomat — davomat menyusi (yoki «🕘 Davomat» tugmasi)",
        "/dhisobot — hozirgi holat (/dhisobot 20.10.2026)",
        "/dkecha · /dhafta · /doy (/doy 2026-09)",
        "/djadval — saytdagi HR bo'limi havolasi",
        "/dtozala — hisobni noldan boshlash (yozuvlar va ballar o'chadi)",
        "",
        "/ishvaqti — har xodimning ish vaqti (tugmalar bilan) · /ishvaqti 5 10:00 19:00",
        "/reyting — shu oy ballari (/reyting yil — yillik) · /ballar — ballar qoidasi",
        "/ball 5 +10 Mijozdan rahmat oldi — qo'shimcha ball (yoki −5)",
        "",
        "/dxodimlar — ro'yxat",
        "/damkun — dam kunlarini tugmalar bilan belgilash",
        "/dam 5 bugun — bir martalik dam kuni",
        "/tatil 5 25.10.2026 30.10.2026 kasal — ta'til / kasallik",
        "/tatillar · /tatil_ochir 3",
        "/dchiqar 5 · /dqayta 5 — ro'yxatdan chiqarish / qaytarish",
        "/qosh — guruhda xodim xabariga javob qilib yozing",
        "",
        "Bayramdan 3 kun oldin bot o'zi so'raydi: dam olinadimi, necha kun.",
        "/bayram 01.01.2027 Yangi yil · /bayramlar · /bayram_ochir 01.01.2027",
        "",
        "/vaqt 09:00 · /kechikish 15 · /dsozlamalar · /dsozla KALIT qiymat",
        "",
        "/ulash — guruhda yozing, bot shu guruhni kuzatadi (har filialda)",
        "/uzish — kuzatishni to'xtatish · /guruhlar — ulangan guruhlar",
    ]
)
