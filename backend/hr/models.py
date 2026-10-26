"""HR — davomat (attendance). Port of davomat.txt (Apps Script), its own tables:
never mixed with the finance (accounting) data.

The Apps Script kept employees, settings, holidays, leaves and today's attendance in
ScriptProperties and wrote finished days to the «Davomat» sheet. Here everything is
a row: Attendance for today is updated live; when a day ends it is «finalized»
(status and points frozen), exactly like the sheet row was written once.
"""

from django.db import models

from .constants import STATUS_CHOICES


class WorkGroup(models.Model):
    """A Telegram work group (filial) the bot watches for video-note reports (/ulash)."""

    chat_id = models.BigIntegerField(unique=True, verbose_name="Telegram chat ID")
    title = models.CharField(max_length=255, verbose_name="Nomi")
    is_active = models.BooleanField(default=True, verbose_name="Kuzatilmoqda")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title"]
        verbose_name = "Ish guruhi"
        verbose_name_plural = "Ish guruhlari"

    def __str__(self):
        return self.title


class Employee(models.Model):
    """A worker who reports in a work group. Most have no site/finance account."""

    telegram_id = models.BigIntegerField(unique=True, verbose_name="Telegram ID")
    number = models.PositiveIntegerField(unique=True, verbose_name="№")  # /dam 5 → #5
    name = models.CharField(max_length=255, verbose_name="Ism")
    username = models.CharField(max_length=255, blank=True, default="", verbose_name="Username")
    is_active = models.BooleanField(default=True, verbose_name="Faol")
    # Can the bot write to them privately? None = not known yet (try), False = blocked.
    can_dm = models.BooleanField(null=True, blank=True, verbose_name="Botga ulangan")
    # None = the general OFF_DAYS setting; [6, 7] = Sat+Sun (1=Mon … 7=Sun)
    off_days = models.JSONField(null=True, blank=True, verbose_name="Dam kunlari")
    group = models.ForeignKey(
        WorkGroup,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
        verbose_name="Filial",
    )
    work_start = models.CharField(
        max_length=5, blank=True, default="", verbose_name="Ish boshlanishi"
    )
    work_end = models.CharField(max_length=5, blank=True, default="", verbose_name="Ish tugashi")
    created_on = models.DateField(null=True, blank=True, verbose_name="Ro'yxatga olingan")
    member = models.OneToOneField(
        "oauth.TelegramMember",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="hr_employee",
        verbose_name="Moliya botidagi a'zo",
    )

    class Meta:
        ordering = ["-is_active", "name"]
        verbose_name = "Xodim (davomat)"
        verbose_name_plural = "Xodimlar (davomat)"

    def __str__(self):
        return self.name


class Attendance(models.Model):
    """One employee, one day. Fields are the Apps Script's `a` object."""

    employee = models.ForeignKey(
        Employee, models.CASCADE, related_name="attendance", verbose_name="Xodim"
    )
    day = models.DateField(db_index=True, verbose_name="Sana")
    status = models.CharField(
        max_length=16, blank=True, default="", choices=STATUS_CHOICES, verbose_name="Holat"
    )
    in_time = models.TimeField(null=True, blank=True, verbose_name="Kelgan vaqti")
    late_min = models.IntegerField(null=True, blank=True, verbose_name="Kechikish (daq)")
    late_reason = models.CharField(
        max_length=16, blank=True, default="", verbose_name="Kechikish sababi"
    )
    late_comment = models.TextField(blank=True, default="", verbose_name="Kechikish izohi")
    link = models.URLField(max_length=300, blank=True, default="", verbose_name="Otchet havolasi")
    work_start = models.CharField(max_length=5, blank=True, default="")
    work_end = models.CharField(max_length=5, blank=True, default="")
    out_time = models.TimeField(null=True, blank=True, verbose_name="Ketgan vaqti")
    early_min = models.IntegerField(null=True, blank=True, verbose_name="Erta ketish (daq)")
    early_reason = models.CharField(
        max_length=16, blank=True, default="", verbose_name="Erta ketish sababi"
    )
    early_comment = models.TextField(blank=True, default="", verbose_name="Erta ketish izohi")
    no_checkin = models.BooleanField(default=False, verbose_name="Kelish qayd etilmagan")
    uniform = models.BooleanField(null=True, blank=True, verbose_name="Forma")
    eta = models.TimeField(null=True, blank=True, verbose_name="Aytgan vaqti")
    eta_sent = models.BooleanField(default=False)
    asked = models.PositiveSmallIntegerField(default=0)
    wait = models.CharField(
        max_length=8, blank=True, default=""
    )  # what the bot waits for: lr/lc/er/ec/reason
    warned = models.BooleanField(default=False)
    off_requested = models.BooleanField(default=False)
    excuse = models.TextField(blank=True, default="", verbose_name="Sabab (kelmadi)")
    note = models.CharField(max_length=255, blank=True, default="", verbose_name="Izoh")
    points = models.IntegerField(null=True, blank=True, verbose_name="Ball")
    finalized = models.BooleanField(default=False, db_index=True)
    group_title = models.CharField(max_length=255, blank=True, default="", verbose_name="Filial")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-day", "employee__name"]
        verbose_name = "Davomat"
        verbose_name_plural = "Davomat"
        constraints = [
            models.UniqueConstraint(fields=["employee", "day"], name="uniq_attendance_day")
        ]

    def __str__(self):
        return f"{self.day} {self.employee}"


class Holiday(models.Model):
    day = models.DateField(unique=True, verbose_name="Sana")
    name = models.CharField(max_length=128, verbose_name="Bayram")

    class Meta:
        ordering = ["day"]
        verbose_name = "Bayram (dam kuni)"
        verbose_name_plural = "Bayramlar"

    def __str__(self):
        return f"{self.day} {self.name}"


class HolidayDecision(models.Model):
    """The admin answered «dam olinadimi?» for this holiday (days=0: we work)."""

    holiday_day = models.DateField(unique=True)
    days = models.PositiveSmallIntegerField(default=0)

    def __str__(self):
        return f"{self.holiday_day}: {self.days}"


class Leave(models.Model):
    number = models.PositiveIntegerField(unique=True, verbose_name="№")
    employee = models.ForeignKey(
        Employee, models.CASCADE, related_name="leaves", verbose_name="Xodim"
    )
    date_from = models.DateField(verbose_name="Dan")
    date_to = models.DateField(verbose_name="Gacha")
    reason = models.CharField(max_length=255, default="ta'til", verbose_name="Sabab")

    class Meta:
        ordering = ["-date_from"]
        verbose_name = "Ta'til"
        verbose_name_plural = "Ta'tillar"

    def __str__(self):
        return f"#{self.number} {self.employee}"


class PointAdjustment(models.Model):
    """/ball 5 +10 Mijozdan rahmat oldi"""

    employee = models.ForeignKey(
        Employee, models.CASCADE, related_name="adjustments", verbose_name="Xodim"
    )
    day = models.DateField(verbose_name="Sana")
    value = models.IntegerField(verbose_name="Ball")
    reason = models.CharField(max_length=255, blank=True, default="", verbose_name="Sabab")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-day", "-id"]
        verbose_name = "Qo'shimcha ball"
        verbose_name_plural = "Qo'shimcha ballar"

    def __str__(self):
        return f"{self.employee} {self.value:+d}"


class Winner(models.Model):
    """«🏆 Oy xodimi» / «👑 Yil xodimi» announced in the groups."""

    KIND = [("m", "Oy xodimi"), ("y", "Yil xodimi")]
    kind = models.CharField(max_length=1, choices=KIND)
    period = models.CharField(max_length=7)  # 2026-10 or 2026
    employee = models.ForeignKey(Employee, models.CASCADE, related_name="wins")
    announced_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period"]
        constraints = [
            models.UniqueConstraint(fields=["kind", "period"], name="uniq_winner_period")
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.period}: {self.employee}"


class HrSetting(models.Model):
    """/dsozla KEY value — only keys from constants.DEFAULTS."""

    key = models.CharField(max_length=32, unique=True)
    value = models.CharField(max_length=255, blank=True, default="")

    def __str__(self):
        return f"{self.key}={self.value}"


class HrState(models.Model):
    """Internal markers: SINCE (count from this day), CURDAY, AWAIT_<admin id>,
    once-per-day job keys."""

    key = models.CharField(max_length=191, unique=True)
    value = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.key
