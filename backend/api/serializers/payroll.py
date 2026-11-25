from rest_framework import serializers

from payroll.models import LineSection, SalarySheet, SheetKind


def _money(**kw):
    return serializers.DecimalField(max_digits=16, decimal_places=2, **kw)


class SheetMemberInSerializer(serializers.Serializer):
    worker = serializers.IntegerField()
    share = serializers.DecimalField(max_digits=7, decimal_places=4)


class SheetLineInSerializer(serializers.Serializer):
    section = serializers.ChoiceField(choices=LineSection.choices)
    order_ref = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    title = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    on_date = serializers.DateField(required=False, allow_null=True, default=None)
    paid_on = serializers.DateField(required=False, allow_null=True, default=None)
    currency = serializers.ChoiceField(choices=["UZS", "USD"], required=False, allow_blank=True, default="")
    amount = _money(required=False, default=0)  # a «Bonuslar» row takes its own
    rate = serializers.DecimalField(
        max_digits=16, decimal_places=4, required=False, allow_null=True, default=None
    )
    # collect row taken from «Bonuslar»: the server fills dates / sum / bonus from it
    order_bonus = serializers.IntegerField(required=False, allow_null=True, default=None)


class SalarySheetWriteSerializer(serializers.Serializer):
    """PATCH body: any header field, plus the whole `members` / `lines` lists when sent."""

    kind = serializers.ChoiceField(choices=SheetKind.choices, required=False)
    section = serializers.CharField(max_length=128, required=False, allow_blank=True)
    position = serializers.CharField(max_length=128, required=False, allow_blank=True)
    month = serializers.RegexField(r"^\d{4}-\d{2}$", required=False)
    period_start = serializers.DateField(required=False)
    period_end = serializers.DateField(required=False)
    usd_rate = serializers.DecimalField(max_digits=16, decimal_places=4, required=False)
    fixed = _money(required=False)
    bonus_percent = serializers.DecimalField(max_digits=7, decimal_places=4, required=False)
    bonus2_percent = serializers.DecimalField(max_digits=7, decimal_places=4, required=False)
    late_days = serializers.IntegerField(min_value=0, max_value=366, required=False)
    late_rate = _money(required=False)
    late_dates = serializers.CharField(max_length=255, required=False, allow_blank=True)
    absent_days = serializers.IntegerField(min_value=0, max_value=366, required=False)
    absent_rate = _money(required=False)
    absent_dates = serializers.CharField(max_length=255, required=False, allow_blank=True)
    instagram_count = serializers.IntegerField(min_value=0, max_value=100000, required=False)
    note = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    members = SheetMemberInSerializer(many=True, required=False)
    lines = SheetLineInSerializer(many=True, required=False)


class SalarySheetCreateSerializer(serializers.Serializer):
    worker = serializers.IntegerField()
    month = serializers.RegexField(r"^\d{4}-\d{2}$", required=False, allow_blank=True)
    kind = serializers.ChoiceField(choices=SheetKind.choices, required=False, allow_blank=True)


class SalarySheetListSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    worker_name = serializers.CharField(source="worker.name", read_only=True)
    month = serializers.SerializerMethodField()
    partners = serializers.SerializerMethodField()
    rest = serializers.SerializerMethodField()
    earned = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = SalarySheet
        fields = [
            "id",
            "number",
            "kind",
            "kind_label",
            "worker",
            "worker_name",
            "partners",
            "month",
            "period_start",
            "period_end",
            "status",
            "status_label",
            "version",
            "returned_note",
            "earned",
            "rest",
            "created_by_name",
            "approved_by_name",
            "approved_at",
            "updated_at",
        ]

    def get_month(self, obj):
        return obj.month.strftime("%Y-%m")

    def get_partners(self, obj):
        return [m.worker.name for m in obj.members.all() if m.worker_id != obj.worker_id]

    def get_rest(self, obj):
        return float((obj.totals or {}).get("rest") or 0)

    def get_earned(self, obj):
        return float((obj.totals or {}).get("earned_total") or 0)

    def get_created_by_name(self, obj):
        return getattr(obj.created_by, "name", "") or ""

    def get_approved_by_name(self, obj):
        return getattr(obj.approved_by, "name", "") or ""
