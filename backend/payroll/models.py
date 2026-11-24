"""Oylik varaqlari: the salary sheet filled in on the site instead of the office's
Excel templates (ODDIY, SBORKA, OFIS, MENEJER, SOTUV, ZAMER). The accountant fills a
sheet, the boss approves it; on approval the sheet is frozen (`snapshot`) and its PDF
lands in the folder of every worker on it. Stage 1 books no money: wallets, order
expenses and the company totals are not touched (payroll/services.py)."""

from django.conf import settings
from django.db import models


class SheetKind(models.TextChoices):
    ODDIY = "oddiy", "Oddiy oylik (fiksa)"
    SBORKA = "sborka", "Sborka / ishbay (buyurtmalar bo'yicha)"
    OFIS = "ofis", "Ofis xodimi (oklad + bonus)"
    MENEJER = "menejer", "Menejer (fiksa + bonus)"
    SOTUV = "sotuv", "Sotuv (fiksa + bonuslar)"
    ZAMER = "zamer", "Zamer (fiksa + bonuslar)"


class SheetStatus(models.TextChoices):
    DRAFT = "draft", "Qoralama"
    SUBMITTED = "submitted", "Tasdiqlashda"
    APPROVED = "approved", "Tasdiqlangan"


class LineSection(models.TextChoices):
    JOB = "job", "Bajarilgan ish (so'm)"
    TAKEN = "taken", "Olingan zakaz ($)"
    DELIVERED = "delivered", "Topshirilgan zakaz ($)"
    COLLECT = "collect", "Pul yechish bonusi"
    DEDUCTION = "deduction", "Ushlanma"
    CAR = "car", "Mashina puli"


class SalarySheet(models.Model):
    number = models.PositiveIntegerField(unique=True, verbose_name="№")
    kind = models.CharField(max_length=16, choices=SheetKind.choices, verbose_name="Turi")
    worker = models.ForeignKey(
        "accounting.Worker",
        models.PROTECT,
        related_name="salary_sheets",
        verbose_name="Xodim",
    )
    section = models.CharField(max_length=128, blank=True, default="", verbose_name="Soha / bo'lim")
    position = models.CharField(max_length=128, blank=True, default="", verbose_name="Lavozim")
    # the month the salary is FOR (1st of it); the folder file is filed under it
    month = models.DateField(db_index=True, verbose_name="Oy")
    period_start = models.DateField(verbose_name="Davr boshi")
    period_end = models.DateField(verbose_name="Davr oxiri")
    usd_rate = models.DecimalField(max_digits=16, decimal_places=4, verbose_name="USD kursi")

    fixed = models.DecimalField(
        max_digits=16, decimal_places=2, default=0, verbose_name="Fiksa / oklad (so'm)"
    )
    # percents as typed: 1.2 = 1.2 %
    bonus_percent = models.DecimalField(
        max_digits=7, decimal_places=4, default=0, verbose_name="Olingan zakaz bonusi (%)"
    )
    bonus2_percent = models.DecimalField(
        max_digits=7, decimal_places=4, default=0, verbose_name="Topshirilgan zakaz bonusi (%)"
    )
    late_days = models.PositiveSmallIntegerField(default=0, verbose_name="Kech qolgan kunlar")
    late_rate = models.DecimalField(
        max_digits=16, decimal_places=2, default=0, verbose_name="Bir kunlik shtraf (so'm)"
    )
    late_dates = models.CharField(max_length=255, blank=True, default="", verbose_name="Sanalar")
    absent_days = models.PositiveSmallIntegerField(default=0, verbose_name="Kelmagan kunlar")
    absent_rate = models.DecimalField(
        max_digits=16, decimal_places=2, default=0, verbose_name="Bir kun uchun (so'm)"
    )
    absent_dates = models.CharField(
        max_length=255, blank=True, default="", verbose_name="Sanalar"
    )
    instagram_count = models.PositiveIntegerField(
        default=0, verbose_name="Instagram istoriyalar soni"
    )
    note = models.TextField(blank=True, default="", verbose_name="Izoh")

    status = models.CharField(
        max_length=16,
        choices=SheetStatus.choices,
        default=SheetStatus.DRAFT,
        db_index=True,
        verbose_name="Holat",
    )
    # how many times it was approved (a re-approval files a new PDF version)
    version = models.PositiveIntegerField(default=0)
    returned_note = models.CharField(
        max_length=500, blank=True, default="", verbose_name="Qaytarish sababi"
    )
    # live totals after every save (the list); the frozen sheet once approved
    totals = models.JSONField(default=dict, blank=True)
    snapshot = models.JSONField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True, related_name="+"
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True, related_name="+"
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-month", "-number"]
        verbose_name = "Oylik varaqasi"
        verbose_name_plural = "Oylik varaqlari"
        permissions = [("approve_salarysheet", "Oylik varaqasini tasdiqlash")]
        indexes = [models.Index(fields=["worker", "month"], name="salarysheet_worker_month")]

    def __str__(self):
        return f"№{self.number} {self.worker} {self.month:%Y-%m}"


class SheetMember(models.Model):
    """SBORKA: the worker and up to two partners sharing the jobs' total."""

    sheet = models.ForeignKey(SalarySheet, models.CASCADE, related_name="members")
    worker = models.ForeignKey("accounting.Worker", models.PROTECT, related_name="+")
    share = models.DecimalField(max_digits=7, decimal_places=4, verbose_name="Ulush (%)")
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(fields=["sheet", "worker"], name="uniq_sheet_member")
        ]


class SheetLine(models.Model):
    sheet = models.ForeignKey(SalarySheet, models.CASCADE, related_name="lines")
    section = models.CharField(max_length=16, choices=LineSection.choices)
    position = models.PositiveSmallIntegerField(default=0)
    order_ref = models.CharField(max_length=32, blank=True, default="", db_index=True)
    order = models.ForeignKey(
        "order.Order", models.SET_NULL, null=True, blank=True, related_name="+"
    )
    title = models.CharField(max_length=255, blank=True, default="", verbose_name="Mijoz / izoh")
    # collect: handed over / money collected; deduction: the date
    on_date = models.DateField(null=True, blank=True)
    paid_on = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="UZS")
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    # deduction in USD: its own rate (empty = the sheet's)
    rate = models.DecimalField(max_digits=16, decimal_places=4, null=True, blank=True)

    class Meta:
        ordering = ["section", "position", "id"]
