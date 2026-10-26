from django.db import migrations

# Frozen copy of accounting/finance_constants.py at the time of this migration:
# later edits to that module must not change what this migration seeds.
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
        {"archive": True, "needs_order": True},
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
        {"archive": True, "needs_order": True},
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
        {"admin_only": True, "excluded": True, "no_order": True},
    ),
    (
        "rahbarga",
        "👔",
        "Rahbarga (shaxsiy)",
        ["rahbarga", "shaxsiy", "шахсий"],
        "#455A64",
        {"excluded": True, "no_order": True},
    ),
    ("boshqa", "📦", "Boshqa", [], "#BDBDBD", {}),
]
INCOME_CATEGORIES = [
    ("avans", "💰", "Avans (yangi zakaz)", "#F5A623", {}),
    ("qoldiq", "✅", "Qoldiq to'lov (bitgan zakaz)", "#2E7D32", {}),
    ("rahbar", "👔", "Rahbardan", "#1E7BEF", {"excluded": True}),
    ("qaytim", "↩️", "Qaytim / vozvrat", "#2ECC71", {}),
    ("boshqa_kirim", "📥", "Boshqa kirim", "#95A5A6", {}),
]
INTERNAL_CATEGORIES = [
    ("otkazma", "🔄", "Xodimlar o'rtasida o'tkazma", "#78909C", {"excluded": True})
]
LEGACY_CATEGORIES = [("adamga", "🤝", "Adamga", "#9E9E9E", {})]
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
CARS = ["Labo — Elyor", "Shineray — Ulug'bek", "Jumaka", "Islom", "Umid"]


def seed(apps, schema_editor):
    Category = apps.get_model("accounting", "FinanceCategory")
    Worker = apps.get_model("accounting", "Worker")
    Car = apps.get_model("accounting", "FinanceCar")

    def put(kind, i, code, emoji, name, keywords, color, flags, active=True):
        Category.objects.get_or_create(
            code=code,
            defaults=dict(
                kind=kind,
                emoji=emoji,
                name=name,
                keywords=keywords,
                color=color,
                ordering=i,
                is_active=active,
                needs_order=flags.get("needs_order", False),
                no_order=flags.get("no_order", False),
                admin_only=flags.get("admin_only", False),
                excluded=flags.get("excluded", False),
                archive=flags.get("archive", False),
            ),
        )

    for i, (code, emoji, name, kw, color, flags) in enumerate(EXPENSE_CATEGORIES):
        put("expense", i, code, emoji, name, kw, color, flags)
    for i, (code, emoji, name, color, flags) in enumerate(INCOME_CATEGORIES):
        put("income", i, code, emoji, name, [], color, flags)
    for i, (code, emoji, name, color, flags) in enumerate(INTERNAL_CATEGORIES):
        put("internal", i, code, emoji, name, [], color, flags)
    for i, (code, emoji, name, color, flags) in enumerate(LEGACY_CATEGORIES):
        put("expense", 100 + i, code, emoji, name, [], color, flags, active=False)

    for i, (group, name, position) in enumerate(WORKERS):
        Worker.objects.get_or_create(
            group=group, name=name, defaults={"position": position, "ordering": i}
        )
    for i, name in enumerate(CARS):
        Car.objects.get_or_create(name=name, defaults={"ordering": i})


class Migration(migrations.Migration):
    dependencies = [("accounting", "0012_finance_models")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
