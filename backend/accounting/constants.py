"""Fixed lists of the finance bot (ported from code.txt). Categories, workers and cars
are seeded into the DB from here once and are editable on the site afterwards."""

from django.db import models


class OpKind(models.TextChoices):
    INCOME = "income", "Kirim"
    EXPENSE = "expense", "Chiqim"


class CategoryKind(models.TextChoices):
    EXPENSE = "expense", "Chiqim"
    INCOME = "income", "Kirim"
    INTERNAL = "internal", "Ichki o'tkazma"


class Currency(models.TextChoices):
    UZS = "UZS", "so'm"
    USD = "USD", "USD"


class PayType(models.TextChoices):
    ADVANCE = "Avans", "Avans"
    SALARY = "Oylik", "Oylik"


# Codes the business rules refer to directly.
CAT_SALARY = "oylik"
CAT_FUEL = "zapravka"
CAT_REWORK = "peredelka"
CAT_TRANSFER = "otkazma"
CAT_FROM_BOSS = "rahbar"
CAT_ADVANCE = "avans"
CAT_REST = "qoldiq"

# [code, emoji, name, keywords, color, flags]
# flags: needs_order (checks warn when missing), no_order (never asked), admin_only,
# excluded (not company expense/income — personal spending, internal moves), archive.
EXPENSE_CATEGORIES = [
    (
        "oylik",
        "👷",
        "Ойлик (ish haqi)",
        ["ойлик", "oylik", "ish haqi", "usta", "montaj", "yordamchi", "зарплата"],
        "#00968F",
        {},
    ),
    (
        "material",
        "🪵",
        "Заказ материал",
        [
            "материал",
            "material",
            "ldsp",
            "лдсп",
            "mdf",
            "мдф",
            "dsp",
            "list",
            "fanera",
            "dvp",
            "kromka",
            "кромка",
            "заказ",
        ],
        "#D9D400",
        {"needs_order": True, "archive": True},
    ),
    (
        "zavod",
        "🏭",
        "Завод продукта",
        ["завод", "zavod", "продукт", "tsex", "цех"],
        "#0A7E8C",
        {"no_order": True},
    ),
    (
        "furnitura",
        "🔩",
        "Furnitura",
        [
            "furnitura",
            "фурнитура",
            "petlya",
            "петля",
            "ruchka",
            "ручка",
            "napravlyayush",
            "blum",
            "oyna",
            "zerkalo",
            "зеркало",
        ],
        "#94A84B",
        {"needs_order": True, "archive": True},
    ),
    (
        "mashina",
        "🚚",
        "Mashina / dostavka",
        [
            "mashina",
            "машина",
            "dostavka",
            "доставка",
            "taksi",
            "такси",
            "gazel",
            "labo",
            "лабо",
            "damas",
            "умид",
            "umid",
        ],
        "#7B4FA0",
        {},
    ),
    (
        "zapravka",
        "⛽",
        "Zapravka",
        [
            "zapravka",
            "заправка",
            "benzin",
            "бензин",
            "metan",
            "метан",
            "propan",
            "пропан",
            "yoqilg",
            "solyarka",
            "дизел",
        ],
        "#F57C00",
        {"no_order": True},
    ),
    (
        "remont",
        "🔧",
        "Remont avto",
        [
            "remont",
            "ремонт",
            "avto",
            "авто",
            "shina",
            "шина",
            "balon",
            "moy ",
            "масло",
            "zapchast",
            "запчаст",
            "vulkan",
        ],
        "#5D6D7E",
        {"no_order": True},
    ),
    (
        "kommunal",
        "💡",
        "Kommunal xizmatlar",
        [
            "kommunal",
            "коммунал",
            "svet",
            "свет",
            "elektr",
            "электр",
            "suv ",
            "вода",
            "gaz uchun",
            "газ",
            "musor",
            "chiqindi",
        ],
        "#1E88E5",
        {"no_order": True},
    ),
    (
        "usluga",
        "🛎",
        "Usluga (xizmatlar)",
        [
            "usluga",
            "услуга",
            "xizmat",
            "хизмат",
            "sverl",
            "raspil",
            "распил",
            "pokraska",
            "покраска",
        ],
        "#26A69A",
        {"archive": True},
    ),
    (
        "smm",
        "📣",
        "СММ / reklama",
        [
            "смм",
            "smm",
            "reklama",
            "реклама",
            "наклейка",
            "nakleyka",
            "target",
            "таргет",
            "instagram",
        ],
        "#E6C200",
        {"no_order": True},
    ),
    (
        "ofis",
        "🗂",
        "Ofis uchun",
        [
            "ofis",
            "офис",
            "podpiska",
            "подписка",
            "claude",
            "claud",
            "internet",
            "интернет",
            "ijara",
            "аренда",
        ],
        "#8B5A4B",
        {"no_order": True},
    ),
    (
        "asbob",
        "🛠",
        "Asbob-uskuna",
        ["asbob", "uskuna", "freza", "фреза", "disk", "диск", "drel", "shurupovert"],
        "#6A00F4",
        {"no_order": True},
    ),
    (
        "ovqat",
        "🍽",
        "Ovqat",
        ["ovqat", "овкат", "obed", "обед", "tushlik", "non", "choy"],
        "#C0392B",
        {"archive": True},
    ),
    (
        "peredelka",
        "🔁",
        "Peredelka (qayta ishlash)",
        ["peredel", "переделк", "qayta ish"],
        "#AD1457",
        {},
    ),
    (
        "uy",
        "🏠",
        "Uy uchun (shaxsiy)",
        ["uy uchun", "уй учун", "uyga", "уйга", "uy xarajat"],
        "#6D4C41",
        {"no_order": True, "admin_only": True, "excluded": True},
    ),
    (
        "rahbarga",
        "👔",
        "Rahbarga (shaxsiy)",
        ["rahbarga", "shaxsiy", "шахсий"],
        "#455A64",
        {"no_order": True, "excluded": True},
    ),
    ("boshqa", "📦", "Boshqa", [], "#BDBDBD", {}),
]

INCOME_CATEGORIES = [
    ("avans", "💰", "Avans (yangi zakaz)", "#F5A623", {}),
    ("qoldiq", "✅", "Qoldiq to'lov (bitgan zakaz)", "#2E7D32", {}),
    # Money the boss hands to a worker: moves cash, is not company income.
    ("rahbar", "👔", "Rahbardan", "#1E7BEF", {"excluded": True}),
    ("qaytim", "↩️", "Qaytim / vozvrat", "#2ECC71", {}),
    ("boshqa_kirim", "📥", "Boshqa kirim", "#95A5A6", {}),
]

INTERNAL_CATEGORIES = [
    ("otkazma", "🔄", "Xodimlar o'rtasida o'tkazma", "#78909C", {"excluded": True}),
]

# Removed long ago in the sheet; kept inactive so old rows still show a name.
LEGACY_CATEGORIES = [
    ("adamga", "🤝", "Adamga", "#9E9E9E", {}),
]

CARS = ["Labo — Elyor", "Shineray — Ulug'bek", "Jumaka", "Islom", "Umid"]

WORKERS = [
    ("1-komanda (sborka-ustanovka)", "Dilmurod", "bosh usta"),
    ("1-komanda (sborka-ustanovka)", "Jamshid", "sherik"),
    ("1-komanda (sborka-ustanovka)", "Jalol", "sherik"),
    ("1-komanda (sborka-ustanovka)", "Nurilla", "sherik"),
    ("2-komanda (sborka-ustanovka)", "Mirjamol", "bosh usta"),
    ("2-komanda (sborka-ustanovka)", "Baxodir", "sherik"),
    ("Zavod", "Jumaka", ""),
    ("Zavod", "Ulug'bek aka", "shofyor"),
    ("Zavod", "Elyor", ""),
    ("Zavod", "Muxabbat opa", ""),
    ("Molyarlar", "Axmadilla", "molyar"),
    ("Molyarlar", "Jasur", "molyar"),
    ("Ofis", "Islom", "CEO"),
    ("Ofis", "Umid", "Pro meneger"),
    ("Ofis", "Maftuna", "Bosh sotuv men."),
    ("Ofis", "Nafisa", "Sotuv men."),
    ("Ofis", "Mumina", "SMM"),
    ("Ofis", "Izzatilla", "Dizayner"),
    ("Ofis", "Doston", "Konstruktor"),
]

# Bonus for the person who collects the final payment: [paid in full within N days, %]
BONUS_TIERS = [(3, 0.5), (7, 0.4), (30, 0.3)]
ARCHIVE_DAYS = 120  # «🗄 Arxiv ID»: orders that became Готов within the last 4 months
