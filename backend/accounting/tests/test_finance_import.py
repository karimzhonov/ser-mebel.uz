from datetime import date, datetime, time
from decimal import Decimal

import pytest
from openpyxl import Workbook

from accounting import services as S
from accounting.finance.importer import Importer, XlsxSource
from accounting.finance_models import (
    ManualOrder,
    MonthReport,
    Operation,
    OrderBonus,
    WarrantyLetter,
)
from oauth.models import TelegramMember

pytestmark = pytest.mark.django_db

TX_HEAD = [
    "ID",
    "Sana",
    "Vaqt",
    "Xodim ID",
    "Xodim",
    "Turi",
    "Summa (so'm)",
    "Valyuta",
    "Asl summa",
    "Kurs",
    "Kategoriya kodi",
    "Kategoriya",
    "Buyurtma ID",
    "Izoh",
    "Chek",
    "Kiritdi",
    "O'chirildi",
    "Ishchi (oylik)",
    "Ish haqi turi",
]


def tx(
    i,
    tid,
    name,
    kind,
    amount,
    cat,
    ord_="",
    com="",
    deleted="",
    worker="",
    cur="UZS",
    orig="",
    rate="",
    author=None,
):
    return [
        i,
        datetime(2026, 9, 10),
        "10:15",
        tid,
        name,
        kind,
        amount,
        cur,
        orig,
        rate,
        cat,
        cat,
        ord_,
        com,
        "",
        author or tid,
        deleted,
        worker,
        "",
    ]


@pytest.fixture
def sheet(tmp_path):
    wb = Workbook()
    wb.remove(wb.active)

    def add(name, head, rows):
        ws = wb.create_sheet(name)
        ws.append(head)
        for r in rows:
            ws.append(r)

    add(
        "Xodimlar",
        ["Telegram ID", "Ism", "Username", "Rol", "Qo'shilgan"],
        [
            [100, "Rahbar", "boss", "admin", "2026-01-01 10:00"],
            [200, "Umid Yusupov", "umid", "xodim", "2026-01-02 10:00"],
            [254366051, "Gafurov Islom", "", "xodim", "2026-01-02 10:00"],
            [400, "Kutayotgan", "", "pending", "2026-01-03 10:00"],
        ],
    )
    add(
        "Sozlamalar",
        ["Kalit", "Qiymat", "Izoh"],
        [
            ["ADMIN_IDS", "100", ""],
            ["CHANNEL_ID", "@sermebel_fin", ""],
            ["ESLATMA_SOAT", 20, ""],
            ["USD_KURS", "", ""],
            ["FIKR_XODIM", "200", ""],
        ],
    )
    add("Ishchilar", ["Bo'lim", "Ism", "Lavozim"], [["Zavod", "Yangi Ishchi", "usta"]])
    add(
        "Buyurtmalar",
        ["ID", "Mijoz", "Telefon", "Tavsif", "Shartnoma (so'm)", "Holat", "Ochilgan", "Yopilgan"],
        [
            ["SM-001", "Eski mijoz", "", "", 5000000, "tugadi", "2025-12-01", "2026-01-10"],
            [406, "Saytdagi", "", "sayt", 0, "jarayonda", "2026-09-01", ""],
        ],
    )
    add(
        "Amallar",
        TX_HEAD,
        [
            tx(1, 200, "Umid", "Kirim", 1000000, "rahbar", author=100),
            tx(2, 200, "Umid", "Chiqim", 350000, "furnitura", "406", "petlya"),
            tx(
                3,
                200,
                "Umid",
                "Chiqim",
                300000,
                "otkazma",
                com="zapravkaga",
                worker="Gafurov Islom",
            ),
            tx(
                4,
                254366051,
                "Islom",
                "Kirim",
                300000,
                "otkazma",
                com="#3: zapravkaga",
                worker="Umid",
            ),
            tx(5, 200, "Umid", "Chiqim", 99999, "ovqat", deleted="Ha"),
            tx(
                6,
                200,
                "Umid",
                "Kirim",
                6000000,
                "qoldiq",
                "SM-001",
                "Pul oldim (mijozdan qoldiq)",
                cur="USD",
                orig=500,
                rate=12000,
            ),
            tx(
                7,
                200,
                "Umid",
                "Chiqim",
                6000000,
                "otkazma",
                "SM-001",
                "Rahbarga topshirdi: SM-001 · Eski mijoz (#6)",
                worker="Rahbar",
            ),
            tx(
                8,
                100,
                "Rahbar",
                "Kirim",
                6000000,
                "otkazma",
                "SM-001",
                "#7: Rahbarga topshirdi: SM-001 · Eski mijoz (#6)",
                worker="Umid",
            ),
            tx(9, 555, "Ketgan xodim", "Chiqim", 10000, "adamga"),
            tx(10, 200, "Umid", "Chiqim", 5000, ""),
            tx(11, 200, "Umid", "Chiqim", 6000, ""),
            ["", datetime(2026, 9, 10), "10:15", 200, "Umid", "Chiqim", 1, "UZS"],
        ],
    )
    add(
        "Oylik hisob",
        ["Xodim ID", "Xodim", "Oy", "Topshirildi", "Qoldiq", "Izoh"],
        [[200, "Umid", "2026-08", "2026-09-01 18:00", 1500, "ok"]],
    )
    add(
        "Bonuslar",
        [
            "Готов sanasi",
            "Buyurtma ID",
            "Mijoz",
            "Umumiy summa",
            "Valyuta",
            "Qoldiq (hozir)",
            "Pul olingan sana",
            "Kun",
            "Foiz",
            "Bonus (so'm)",
            "Holat",
            "Izoh",
            "Kimga",
        ],
        [
            [
                date(2026, 9, 1),
                "389",
                "Назира",
                4200,
                "USD",
                0,
                date(2026, 9, 3),
                2,
                0.005,
                252000,
                "✅ Olindi",
                "",
                "Umid Yusupov",
            ]
        ],
    )
    add(
        "Kafolat xatlari",
        ["Buyurtma ID", "Mijoz", "Готов sanasi", "Holat", "Berilgan sana", "Kim berdi", "Izoh"],
        [["389", "Назира", date(2026, 9, 1), "✅ Berildi", date(2026, 9, 2), "Umid", ""]],
    )
    add(
        "Saytga kiritish",
        [
            "Kod",
            "Olingan sana",
            "Buyurtma ID",
            "Mijoz",
            "Olingan summa",
            "Kim oldi",
            "Qoldiq (botda)",
            "Holat",
            "Kiritilgan sana",
            "Kim kiritdi",
        ],
        [
            [
                "sk1a",
                date(2026, 9, 3),
                "389",
                "Назира",
                "500 USD",
                "Umid",
                "0",
                "⏳ Kiritilmagan",
                "",
                "",
            ]
        ],
    )
    add(
        "Mijoz fikrlari",
        [
            "Buyurtma ID",
            "Mijoz",
            "Telefon",
            "Готов sanasi",
            "So'ralgan sana",
            "Holat",
            "Olingan sana",
            "Kim oldi",
            "Fikr (izoh)",
            "Skrinshot",
        ],
        [
            [
                "389",
                "Назира",
                "",
                date(2026, 9, 1),
                date(2026, 9, 4),
                "✅ Olindi",
                date(2026, 9, 5),
                "Umid",
                "Zo'r",
                '=HYPERLINK("https://drive.google.com/x";"📷 Ko\'rish")',
            ]
        ],
    )
    add("Davomat", ["Sana", "Xodim"], [["2026-09-10", "HR data must not be read"]])
    p = tmp_path / "book.xlsx"
    wb.save(p)
    return str(p)


def test_import_everything_and_verify(sheet, site_order):
    rep = Importer(XlsxSource(sheet)).run()
    assert rep.ok(), rep.text()
    assert Operation.objects.count() == 11
    assert Operation.objects.get(number=10).category.code == "boshqa"  # empty code
    assert any("ID bo'sh" in w for w in rep.warnings)  # the id-less row is reported
    boss = TelegramMember.objects.get(telegram_id=100)
    umid = TelegramMember.objects.get(telegram_id=200)
    islom = TelegramMember.objects.get(telegram_id=254366051)
    assert (
        boss.role == "admin"
        and umid.is_bonus_receiver
        and umid.is_feedback
        and islom.is_deadline_receiver
    )
    assert TelegramMember.objects.get(telegram_id=555).role == "blocked"  # rebuilt from Amallar
    assert S.balance(umid) == Decimal("1000000") - 350000 - 300000 + 6000000 - 6000000 - 11000
    assert Operation.objects.get(number=4).pair.number == 3
    assert Operation.objects.get(number=6).handover == "accepted"
    assert not S.handover_pending()
    assert Operation.objects.get(number=2).order_id == site_order.id
    assert Operation.objects.get(number=5).is_deleted
    assert Operation.objects.get(number=9).category.is_active is False  # old «adamga» kept
    assert Operation.objects.get(number=1).time == time(10, 15)
    assert ManualOrder.objects.filter(ref="SM-001", is_closed=True).exists()
    assert not ManualOrder.objects.filter(ref="406").exists()  # a site order, not manual
    assert MonthReport.objects.get().month == "2026-08"
    bn = OrderBonus.objects.get()
    assert bn.percent == Decimal("0.5") and bn.status == "done"
    assert WarrantyLetter.objects.get().given
    from accounting.finance_models import ClientFeedback

    assert ClientFeedback.objects.get().screenshot_url == "https://drive.google.com/x"
    from constance import config

    assert config.FIN_REMINDER_HOUR == 20 and config.FIN_CHANNEL_ID == "@sermebel_fin"


def test_reimport_is_idempotent(sheet, site_order):
    Importer(XlsxSource(sheet)).run()
    n = Operation.objects.count()
    rep = Importer(XlsxSource(sheet)).run()
    assert rep.ok() and Operation.objects.count() == n and TelegramMember.objects.count() == 5


def test_reimport_never_overwrites_new_bot_rows(sheet, site_order, members):
    S.create_operation(
        member=members[1], kind="expense", amount=777, category_code="ovqat", number=2
    )
    rep = Importer(XlsxSource(sheet)).run()
    assert not rep.ok()  # the sheet total no longer matches — and it says so
    assert any("band" in w for w in rep.warnings)
    assert Operation.objects.get(number=2).amount == 777


def test_management_command_dry_run(sheet, site_order):
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    call_command("import_finance_sheet", xlsx=sheet, dry_run=True, stdout=out)
    assert "DRY RUN" in out.getvalue() and "✅" in out.getvalue()
    assert not Operation.objects.exists()
