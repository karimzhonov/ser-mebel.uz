from rest_framework import serializers

from hr import services as S
from hr.models import Attendance, Employee, Holiday, Leave, PointAdjustment, Winner, WorkGroup


class WorkGroupSerializer(serializers.ModelSerializer):
    employees = serializers.IntegerField(source="n_employees", read_only=True, default=0)

    class Meta:
        model = WorkGroup
        fields = ["id", "chat_id", "title", "is_active", "employees"]
        read_only_fields = ["chat_id", "employees"]


class EmployeeSerializer(serializers.ModelSerializer):
    group_title = serializers.CharField(source="group.title", read_only=True, default="")
    hours = serializers.SerializerMethodField()
    off_days_effective = serializers.SerializerMethodField()
    member_name = serializers.CharField(source="member.name", read_only=True, default=None)

    class Meta:
        model = Employee
        fields = [
            "id",
            "telegram_id",
            "number",
            "name",
            "username",
            "is_active",
            "can_dm",
            "off_days",
            "off_days_effective",
            "group",
            "group_title",
            "work_start",
            "work_end",
            "hours",
            "created_on",
            "member",
            "member_name",
        ]
        read_only_fields = ["number", "can_dm", "created_on", "member"]

    def validate_telegram_id(self, v):
        if self.instance and v != self.instance.telegram_id:
            raise serializers.ValidationError(
                "Telegram ID o'zgarmaydi (xabarlar boshqa odamga ketadi)."
            )
        return v

    def get_hours(self, obj):
        return S.emp_hours(obj)

    def get_off_days_effective(self, obj):
        return S.emp_off_days(obj)

    def validate_off_days(self, v):
        if v is None:
            return None
        if not isinstance(v, list) or any(not isinstance(d, int) or not 1 <= d <= 7 for d in v):
            raise serializers.ValidationError("1 (Du) … 7 (Ya) sonlar ro'yxati.")
        return sorted(set(v))

    def validate(self, attrs):
        ws = attrs.get("work_start", getattr(self.instance, "work_start", ""))
        we = attrs.get("work_end", getattr(self.instance, "work_end", ""))
        for k, v in (("work_start", ws), ("work_end", we)):
            if v and S.parse_hm(v) is None:
                raise serializers.ValidationError({k: "Vaqt 09:00 formatida."})
        if bool(ws) != bool(we):
            raise serializers.ValidationError(
                {
                    "work_end": "Boshlanish va tugash birga beriladi (yoki ikkalasi bo'sh — umumiy vaqt)."
                }
            )
        if ws and we and S.parse_hm(we) <= S.parse_hm(ws):
            raise serializers.ValidationError(
                {"work_end": "Tugash boshlanishdan keyin bo'lishi kerak."}
            )
        if ws:
            attrs["work_start"], attrs["work_end"] = S.hm_str(S.parse_hm(ws)), S.hm_str(
                S.parse_hm(we)
            )
        return attrs


class AttendanceSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.name", read_only=True)
    employee_number = serializers.IntegerField(source="employee.number", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Attendance
        fields = [
            "id",
            "employee",
            "employee_name",
            "employee_number",
            "day",
            "status",
            "status_label",
            "in_time",
            "late_min",
            "late_reason",
            "late_comment",
            "out_time",
            "early_min",
            "early_reason",
            "early_comment",
            "uniform",
            "eta",
            "excuse",
            "note",
            "link",
            "work_start",
            "work_end",
            "points",
            "finalized",
            "group_title",
        ]
        read_only_fields = fields


class AttendanceEditSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[c[0] for c in Attendance._meta.get_field("status").choices], required=False
    )
    in_time = serializers.TimeField(required=False, allow_null=True)
    out_time = serializers.TimeField(required=False, allow_null=True)
    late_min = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    late_reason = serializers.ChoiceField(choices=["", "Sababli", "Sababsiz"], required=False)
    late_comment = serializers.CharField(required=False, allow_blank=True)
    early_min = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    early_reason = serializers.ChoiceField(choices=["", "Sababli", "Sababsiz"], required=False)
    early_comment = serializers.CharField(required=False, allow_blank=True)
    uniform = serializers.BooleanField(required=False, allow_null=True)
    excuse = serializers.CharField(required=False, allow_blank=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=255)


class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = ["id", "day", "name"]


class LeaveSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.name", read_only=True)

    class Meta:
        model = Leave
        fields = ["id", "number", "employee", "employee_name", "date_from", "date_to", "reason"]
        read_only_fields = ["number"]

    def validate(self, attrs):
        f = attrs.get("date_from", getattr(self.instance, "date_from", None))
        t = attrs.get("date_to", getattr(self.instance, "date_to", None))
        if f and t and t < f:
            raise serializers.ValidationError({"date_to": "Tugash sanasi boshlanishdan oldin."})
        return attrs


class PointAdjustmentSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.name", read_only=True)

    class Meta:
        model = PointAdjustment
        fields = ["id", "employee", "employee_name", "day", "value", "reason", "created_at"]
        read_only_fields = ["created_at"]

    def validate_value(self, v):
        if not v or abs(v) > 100:
            raise serializers.ValidationError("1 dan 100 gacha (yoki −1 dan −100 gacha).")
        return v


class WinnerSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.name", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = Winner
        fields = ["id", "kind", "kind_label", "period", "employee", "employee_name", "announced_at"]
