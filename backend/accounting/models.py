"""Moliya (finance) models — port of the Google Sheets tables of code.txt:
per-person wallets, operations, transfers, requests, month reports, bonuses."""

from decimal import Decimal

from django.db import models

from .constants import CategoryKind, Currency, OpKind, PayType


class FinanceCategory(models.Model):
    code = models.SlugField(max_length=32, unique=True, verbose_name="Kod")
    kind = models.CharField(max_length=16, choices=CategoryKind.choices, verbose_name="Turi")
    emoji = models.CharField(max_length=8, blank=True, default="", verbose_name="Emoji")
    name = models.CharField(max_length=128, verbose_name="Nomi")
    keywords = models.JSONField(default=list, blank=True, verbose_name="Kalit so'zlar")
    color = models.CharField(max_length=16, default="#BDBDBD", verbose_name="Rang")
    needs_order = models.BooleanField(
        default=False, verbose_name="Buyurtmasiz bo'lsa ogohlantirish"
    )
    no_order = models.BooleanField(default=False, verbose_name="Buyurtma so'ralmaydi")
    admin_only = models.BooleanField(default=False, verbose_name="Faqat rahbar")
    excluded = models.BooleanField(
        default=False, verbose_name="Kompaniya xarajati/daromadiga kirmaydi"
    )
    archive = models.BooleanField(default=False, verbose_name="«Arxiv ID» tugmasi")
    ordering = models.PositiveIntegerField(default=0, verbose_name="Tartib")
    is_active = models.BooleanField(default=True, verbose_name="Faol")

    class Meta:
        ordering = ["kind", "ordering", "id"]
        verbose_name = "Moliya kategoriyasi"
        verbose_name_plural = "Moliya kategoriyalari"

    def __str__(self):
        return f"{self.emoji} {self.name}".strip()

    @property
    def label(self) -> str:
        return str(self)


class Worker(models.Model):
    """«Ishchilar»: people who get salary (oylik) — most have no Telegram/site account."""

    group = models.CharField(max_length=128, verbose_name="Bo'lim")
    name = models.CharField(max_length=128, verbose_name="Ism")
    position = models.CharField(max_length=128, blank=True, default="", verbose_name="Lavozim")
    ordering = models.PositiveIntegerField(default=0, verbose_name="Tartib")
    is_active = models.BooleanField(default=True, verbose_name="Faol")
    # «Oylik chiqarish»: the day of the month the salary is paid (the accountant is
    # reminded the day before) and this person's own Excel template (fixed / bonus /
    # task pay differ). The template is kept in the DB, not in public /media.
    pay_day = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="Oylik kuni (oyning sanasi)"
    )
    salary_template = models.BinaryField(null=True, blank=True, editable=False)
    salary_template_name = models.CharField(
        max_length=255, blank=True, default="", verbose_name="Oylik shabloni"
    )
    salary_template_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["ordering", "id"]
        verbose_name = "Ishchi"
        verbose_name_plural = "Ishchilar"
        constraints = [
            models.UniqueConstraint(fields=["group", "name"], name="uniq_worker_group_name")
        ]

    def __str__(self):
        return self.name


class FinanceCar(models.Model):
    """Zapravka: which car / driver."""

    name = models.CharField(max_length=128, unique=True, verbose_name="Mashina / kim")
    ordering = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True, verbose_name="Faol")

    class Meta:
        ordering = ["ordering", "id"]
        verbose_name = "Mashina"
        verbose_name_plural = "Mashinalar"

    def __str__(self):
        return self.name


class ManualOrder(models.Model):
    """Order ids used by the finance bot that do not exist on the site (SM-001 …,
    or ids typed by hand). Site orders are read from order.Order directly."""

    ref = models.CharField(max_length=32, unique=True, verbose_name="ID")
    client = models.CharField(max_length=255, blank=True, default="", verbose_name="Mijoz")
    phone = models.CharField(max_length=64, blank=True, default="", verbose_name="Telefon")
    price = models.DecimalField(
        max_digits=16, decimal_places=2, default=0, verbose_name="Shartnoma (so'm)"
    )
    is_closed = models.BooleanField(default=False, verbose_name="Yopilgan")
    opened = models.DateField(null=True, blank=True, verbose_name="Ochilgan")
    closed = models.DateField(null=True, blank=True, verbose_name="Yopilgan sana")

    class Meta:
        ordering = ["-id"]
        verbose_name = "Qo'lda kiritilgan buyurtma"
        verbose_name_plural = "Qo'lda kiritilgan buyurtmalar"

    def __str__(self):
        return f"{self.ref} · {self.client}"


class Operation(models.Model):
    """One row of «Amallar»: money that came into / went out of a member's wallet."""

    number = models.PositiveIntegerField(unique=True, verbose_name="№")
    date = models.DateField(db_index=True, verbose_name="Sana")
    time = models.TimeField(null=True, blank=True, verbose_name="Vaqt")
    member = models.ForeignKey(
        "oauth.TelegramMember",
        models.PROTECT,
        related_name="operations",
        verbose_name="Hamyon egasi",
    )
    author = models.ForeignKey(
        "oauth.TelegramMember",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="authored_operations",
        verbose_name="Kiritdi",
    )
    site_user = models.ForeignKey(
        "oauth.User",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Saytda kiritdi/o'zgartirdi",
    )
    kind = models.CharField(
        max_length=16, choices=OpKind.choices, db_index=True, verbose_name="Turi"
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2, verbose_name="Summa (so'm)")
    currency = models.CharField(
        max_length=3, choices=Currency.choices, default=Currency.UZS, verbose_name="Valyuta"
    )
    orig_amount = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True, verbose_name="Asl summa"
    )
    rate = models.DecimalField(
        max_digits=16, decimal_places=4, null=True, blank=True, verbose_name="Kurs"
    )
    category = models.ForeignKey(
        FinanceCategory, models.PROTECT, related_name="operations", verbose_name="Kategoriya"
    )
    order = models.ForeignKey(
        "order.Order",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="finance_operations",
        verbose_name="Buyurtma",
    )
    # Always the id as typed/shown in the bot («406», «SM-003»); `order` is filled when
    # it is a site order_number.
    order_ref = models.CharField(
        max_length=32, blank=True, default="", db_index=True, verbose_name="Buyurtma ID"
    )
    comment = models.TextField(blank=True, default="", verbose_name="Izoh")
    receipt_file_id = models.CharField(
        max_length=255, blank=True, default="", verbose_name="Chek (Telegram fayl)"
    )
    # Who got the salary / which car / the other side of a transfer.
    worker = models.CharField(
        max_length=255, blank=True, default="", verbose_name="Ishchi / mashina / kimga"
    )
    pay_type = models.CharField(
        max_length=16, choices=PayType.choices, blank=True, default="", verbose_name="Ish haqi turi"
    )
    pair = models.OneToOneField(
        "self",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="pair_of",
        verbose_name="O'tkazmaning juft yozuvi",
    )
    # Money a worker collected from a client and has to hand to the boss (/topshiruv).
    handover = models.CharField(
        max_length=16,
        blank=True,
        default="",
        choices=[("", "—"), ("accepted", "Qabul qilindi"), ("deleted", "Alohida kiritilgan")],
        verbose_name="Rahbarga topshirish",
    )
    is_deleted = models.BooleanField(default=False, db_index=True, verbose_name="O'chirildi")
    deleted_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(
        max_length=8,
        default="bot",
        choices=[("bot", "Telegram"), ("site", "Sayt"), ("import", "Google jadval")],
        verbose_name="Manba",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-number"]
        verbose_name = "Amal"
        verbose_name_plural = "Amallar"
        permissions = [("view_all_operations", "Barcha hamyonlar va amallarni ko'rish")]
        indexes = [
            models.Index(fields=["member", "date"]),
            models.Index(fields=["category", "date"]),
        ]

    def __str__(self):
        return f"#{self.number} {self.get_kind_display()} {self.amount}"

    @property
    def signed_amount(self) -> Decimal:
        return self.amount if self.kind == OpKind.INCOME else -self.amount


class MonthReport(models.Model):
    """«Oylik hisob»: a member confirms the month's entries are complete."""

    member = models.ForeignKey(
        "oauth.TelegramMember", models.CASCADE, related_name="month_reports", verbose_name="Xodim"
    )
    month = models.CharField(max_length=7, verbose_name="Oy (YYYY-MM)")
    submitted_at = models.DateTimeField(verbose_name="Topshirildi")
    balance = models.DecimalField(max_digits=16, decimal_places=2, default=0, verbose_name="Qoldiq")
    note = models.TextField(blank=True, default="", verbose_name="Izoh")

    class Meta:
        ordering = ["-month", "member__name"]
        verbose_name = "Oylik hisob"
        verbose_name_plural = "Oylik hisoblar"
        constraints = [
            models.UniqueConstraint(fields=["member", "month"], name="uniq_month_report")
        ]

    def __str__(self):
        return f"{self.member} · {self.month}"


class MoneyRequest(models.Model):
    """«🙏 Rahbardan pul so'rash»."""

    STATUS = [("pending", "Kutmoqda"), ("given", "Berildi"), ("rejected", "Rad etildi")]

    number = models.PositiveIntegerField(unique=True, verbose_name="№")
    member = models.ForeignKey(
        "oauth.TelegramMember", models.CASCADE, related_name="money_requests", verbose_name="Xodim"
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2, verbose_name="Summa (so'm)")
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.UZS)
    orig_amount = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    rate = models.DecimalField(max_digits=16, decimal_places=4, null=True, blank=True)
    reason = models.TextField(blank=True, default="", verbose_name="Sabab")
    status = models.CharField(
        max_length=16, choices=STATUS, default="pending", db_index=True, verbose_name="Holat"
    )
    answer = models.CharField(max_length=255, blank=True, default="", verbose_name="Javob")
    answered_by = models.ForeignKey(
        "oauth.TelegramMember",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Javob berdi",
    )
    operation = models.ForeignKey(
        Operation, models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # [[chat_id, message_id], …] of the admin messages, edited when answered.
    admin_messages = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-number"]
        verbose_name = "Pul so'rovi"
        verbose_name_plural = "Pul so'rovlari"

    def __str__(self):
        return f"#{self.number} {self.member}"


class OrderBonus(models.Model):
    """«Bonuslar»: an order became Готов → the bonus receiver collects the rest of the
    money; the faster it is paid in full, the bigger the bonus (BONUS_TIERS)."""

    STATUS = [
        ("waiting", "⏳ Kutilmoqda"),
        ("done", "✅ Olindi"),
        ("expired", "❌ 30 kundan o'tdi"),
    ]

    order_ref = models.CharField(max_length=32, unique=True, verbose_name="Buyurtma ID")
    order = models.ForeignKey(
        "order.Order", models.SET_NULL, null=True, blank=True, related_name="+"
    )
    client = models.CharField(max_length=255, blank=True, default="", verbose_name="Mijoz")
    description = models.CharField(
        max_length=255, blank=True, default="", verbose_name="Mebel turi"
    )
    phone = models.CharField(max_length=64, blank=True, default="")
    total = models.DecimalField(
        max_digits=16, decimal_places=2, default=0, verbose_name="Umumiy summa"
    )
    currency = models.CharField(
        max_length=3, choices=Currency.choices, default=Currency.UZS, verbose_name="Valyuta"
    )
    ready_date = models.DateField(verbose_name="Готов sanasi")
    rest = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True, verbose_name="Qoldiq (oxirgi)"
    )
    # «💰 Pul oldim» entries made before the site's «Полученная сумма» was updated.
    rest_base = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    got = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    got_text = models.CharField(max_length=255, blank=True, default="")
    reminders = models.JSONField(default=dict, blank=True)  # {"d3": "2026-10-01", …}
    zero_notified = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=STATUS, default="waiting", db_index=True, verbose_name="Holat"
    )
    paid_date = models.DateField(null=True, blank=True, verbose_name="Pul olingan sana")
    days = models.IntegerField(null=True, blank=True, verbose_name="Kun")
    percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Foiz"
    )
    bonus = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True, verbose_name="Bonus (so'm)"
    )
    note = models.CharField(max_length=255, blank=True, default="", verbose_name="Izoh")
    receiver = models.CharField(max_length=255, blank=True, default="", verbose_name="Kimga")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-ready_date", "-id"]
        verbose_name = "Bonus"
        verbose_name_plural = "Bonuslar"

    def __str__(self):
        return f"{self.order_ref} · {self.client}"


class WarrantyLetter(models.Model):
    """«Kafolat xatlari»: was the warranty letter handed to the client."""

    order_ref = models.CharField(max_length=32, unique=True, verbose_name="Buyurtma ID")
    client = models.CharField(max_length=255, blank=True, default="", verbose_name="Mijoz")
    ready_date = models.DateField(null=True, blank=True, verbose_name="Готов sanasi")
    given = models.BooleanField(default=False, verbose_name="Berildi")
    given_at = models.DateField(null=True, blank=True, verbose_name="Berilgan sana")
    given_by = models.CharField(max_length=255, blank=True, default="", verbose_name="Kim berdi")
    note = models.CharField(max_length=255, blank=True, default="", verbose_name="Izoh")

    class Meta:
        ordering = ["given", "-ready_date"]
        verbose_name = "Kafolat xati"
        verbose_name_plural = "Kafolat xatlari"

    def __str__(self):
        return f"{self.order_ref} · {self.client}"


class SiteEntryTask(models.Model):
    """«Saytga kiritish»: money was collected — someone must update the order's paid
    amount on the site."""

    code = models.CharField(max_length=32, unique=True, verbose_name="Kod")
    date = models.DateField(verbose_name="Olingan sana")
    order_ref = models.CharField(max_length=32, verbose_name="Buyurtma ID")
    client = models.CharField(max_length=255, blank=True, default="", verbose_name="Mijoz")
    sum_text = models.CharField(
        max_length=255, blank=True, default="", verbose_name="Olingan summa"
    )
    taken_by = models.CharField(max_length=255, blank=True, default="", verbose_name="Kim oldi")
    rest_text = models.CharField(max_length=255, blank=True, default="", verbose_name="Qoldiq")
    is_done = models.BooleanField(default=False, db_index=True, verbose_name="Kiritildi")
    done_at = models.DateField(null=True, blank=True, verbose_name="Kiritilgan sana")
    done_by = models.CharField(max_length=255, blank=True, default="", verbose_name="Kim kiritdi")
    reminded = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["is_done", "-date", "-id"]
        verbose_name = "Saytga kiritish"
        verbose_name_plural = "Saytga kiritish"

    def __str__(self):
        return f"{self.order_ref} · {self.sum_text}"


class ClientFeedback(models.Model):
    """«Mijoz fikrlari»: 3 days after Готов ask the client for feedback."""

    STATUS = [("scheduled", "Rejada"), ("asked", "⏳ Kutilmoqda"), ("received", "✅ Olindi")]

    order_ref = models.CharField(max_length=32, unique=True, verbose_name="Buyurtma ID")
    client = models.CharField(max_length=255, blank=True, default="", verbose_name="Mijoz")
    phone = models.CharField(max_length=64, blank=True, default="", verbose_name="Telefon")
    ready_date = models.DateField(null=True, blank=True, verbose_name="Готов sanasi")
    asked_date = models.DateField(null=True, blank=True, verbose_name="So'ralgan sana")
    status = models.CharField(
        max_length=16, choices=STATUS, default="scheduled", db_index=True, verbose_name="Holat"
    )
    received_date = models.DateField(null=True, blank=True, verbose_name="Olingan sana")
    received_by = models.CharField(max_length=255, blank=True, default="", verbose_name="Kim oldi")
    text = models.TextField(blank=True, default="", verbose_name="Fikr")
    screenshot_file_id = models.CharField(max_length=255, blank=True, default="")
    screenshot_url = models.URLField(
        max_length=500, blank=True, default="", verbose_name="Skrinshot havolasi"
    )
    reminded = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-ready_date", "-id"]
        verbose_name = "Mijoz fikri"
        verbose_name_plural = "Mijoz fikrlari"

    def __str__(self):
        return f"{self.order_ref} · {self.client}"


class FinanceJobRun(models.Model):
    """Once-per-day (or once-ever) markers for scheduled jobs and reminders."""

    key = models.CharField(max_length=191, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.key
