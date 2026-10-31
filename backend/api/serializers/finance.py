from rest_framework import serializers

from accounting.models import (
    ClientFeedback,
    FinanceCar,
    FinanceCategory,
    ManualOrder,
    MoneyRequest,
    MonthReport,
    Operation,
    OrderBonus,
    SiteEntryTask,
    WarrantyLetter,
    Worker,
)
from oauth.models import TelegramMember, User

from .common import UserShortSerializer


class TelegramMemberSerializer(serializers.ModelSerializer):
    user_detail = UserShortSerializer(source="user", read_only=True)
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False, allow_null=True
    )
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    is_task_only = serializers.BooleanField(read_only=True)
    has_wallet = serializers.BooleanField(read_only=True)

    class Meta:
        model = TelegramMember
        fields = [
            "id",
            "telegram_id",
            "name",
            "username",
            "role",
            "role_label",
            "user",
            "user_detail",
            "is_site_entry",
            "is_feedback",
            "is_bonus_receiver",
            "is_deadline_receiver",
            "is_accountant",
            "is_task_only",
            "has_wallet",
            "joined_at",
        ]
        read_only_fields = ["username", "joined_at"]

    def validate_user(self, user):
        if (
            user
            and TelegramMember.objects.filter(user=user)
            .exclude(pk=getattr(self.instance, "pk", None))
            .exists()
        ):
            raise serializers.ValidationError("Bu foydalanuvchi boshqa Telegram a'zoga ulangan.")
        return user


class MemberShortSerializer(serializers.ModelSerializer):
    class Meta:
        model = TelegramMember
        fields = ["id", "telegram_id", "name", "role"]


class FinanceCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = FinanceCategory
        fields = [
            "id",
            "code",
            "kind",
            "emoji",
            "name",
            "keywords",
            "color",
            "needs_order",
            "no_order",
            "admin_only",
            "excluded",
            "archive",
            "ordering",
            "is_active",
        ]

    def validate_code(self, code):
        if self.instance and self.instance.code != code:
            raise serializers.ValidationError(
                "Kodni o'zgartirib bo'lmaydi (eski yozuvlar unga bog'langan)."
            )
        return code


class WorkerSerializer(serializers.ModelSerializer):
    has_template = serializers.SerializerMethodField()

    class Meta:
        model = Worker
        fields = [
            "id",
            "group",
            "name",
            "position",
            "ordering",
            "is_active",
            "pay_day",
            "has_template",
            "salary_template_name",
            "salary_template_at",
        ]
        read_only_fields = ["salary_template_name", "salary_template_at"]

    def get_has_template(self, w) -> bool:
        return bool(w.salary_template_name)

    def validate_pay_day(self, v):
        if v is not None and not 1 <= v <= 31:
            raise serializers.ValidationError("Oyning kuni: 1 dan 31 gacha.")
        return v


class FinanceCarSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinanceCar
        fields = ["id", "name", "ordering", "is_active"]


class ManualOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = ManualOrder
        fields = ["id", "ref", "client", "phone", "price", "is_closed", "opened", "closed"]


class OperationSerializer(serializers.ModelSerializer):
    member_detail = MemberShortSerializer(source="member", read_only=True)
    author_detail = MemberShortSerializer(source="author", read_only=True)
    site_user_detail = UserShortSerializer(source="site_user", read_only=True)
    category_detail = FinanceCategorySerializer(source="category", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    source_label = serializers.CharField(source="get_source_display", read_only=True)
    has_receipt = serializers.SerializerMethodField()
    pair_number = serializers.SerializerMethodField()

    class Meta:
        model = Operation
        fields = [
            "id",
            "number",
            "date",
            "time",
            "kind",
            "kind_label",
            "amount",
            "currency",
            "orig_amount",
            "rate",
            "category",
            "category_detail",
            "order",
            "order_ref",
            "comment",
            "worker",
            "pay_type",
            "member",
            "member_detail",
            "author_detail",
            "site_user_detail",
            "has_receipt",
            "pair_number",
            "handover",
            "is_deleted",
            "source",
            "source_label",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_has_receipt(self, obj):
        return bool(obj.receipt_file_id)

    def get_pair_number(self, obj):
        if obj.pair_id:
            return obj.pair.number
        other = getattr(obj, "pair_of", None)
        return other.number if other else None


class OperationWriteSerializer(serializers.Serializer):
    """Input for create/update; the rules are in accounting.services."""

    member = serializers.PrimaryKeyRelatedField(
        queryset=TelegramMember.objects.all(), required=False
    )
    kind = serializers.ChoiceField(choices=["income", "expense"], required=False)
    category_code = serializers.SlugField(required=False)
    amount = serializers.DecimalField(
        max_digits=16, decimal_places=2, required=False, allow_null=True
    )
    currency = serializers.ChoiceField(choices=["UZS", "USD"], required=False)
    orig_amount = serializers.DecimalField(
        max_digits=16, decimal_places=2, required=False, allow_null=True
    )
    rate = serializers.DecimalField(
        max_digits=16, decimal_places=4, required=False, allow_null=True
    )
    order_ref = serializers.CharField(max_length=32, required=False, allow_blank=True)
    comment = serializers.CharField(required=False, allow_blank=True)
    worker = serializers.CharField(max_length=255, required=False, allow_blank=True)
    pay_type = serializers.ChoiceField(choices=["", "Avans", "Oylik"], required=False)
    date = serializers.DateField(required=False)


class TransferSerializer(serializers.Serializer):
    sender = serializers.PrimaryKeyRelatedField(queryset=TelegramMember.objects.all())
    receiver = serializers.PrimaryKeyRelatedField(queryset=TelegramMember.objects.all())
    amount = serializers.DecimalField(max_digits=16, decimal_places=2)
    comment = serializers.CharField(required=False, allow_blank=True, default="")


class MonthReportSerializer(serializers.ModelSerializer):
    member_detail = MemberShortSerializer(source="member", read_only=True)

    class Meta:
        model = MonthReport
        fields = ["id", "member", "member_detail", "month", "submitted_at", "balance", "note"]
        read_only_fields = ["submitted_at", "balance"]


class MoneyRequestSerializer(serializers.ModelSerializer):
    member_detail = MemberShortSerializer(source="member", read_only=True)
    answered_by_detail = MemberShortSerializer(source="answered_by", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    operation_number = serializers.IntegerField(
        source="operation.number", read_only=True, default=None
    )

    class Meta:
        model = MoneyRequest
        fields = [
            "id",
            "number",
            "member",
            "member_detail",
            "amount",
            "currency",
            "orig_amount",
            "rate",
            "reason",
            "status",
            "status_label",
            "answer",
            "answered_by_detail",
            "operation_number",
            "created_at",
            "answered_at",
        ]
        read_only_fields = fields


class OrderBonusSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = OrderBonus
        fields = [
            "id",
            "order_ref",
            "client",
            "description",
            "phone",
            "total",
            "currency",
            "ready_date",
            "rest",
            "got_text",
            "status",
            "status_label",
            "paid_date",
            "days",
            "percent",
            "bonus",
            "note",
            "receiver",
        ]
        read_only_fields = [f for f in fields if f not in ("note",)]


class WarrantyLetterSerializer(serializers.ModelSerializer):
    class Meta:
        model = WarrantyLetter
        fields = [
            "id",
            "order_ref",
            "client",
            "ready_date",
            "given",
            "given_at",
            "given_by",
            "note",
        ]
        read_only_fields = ["order_ref", "client", "ready_date", "given", "given_at", "given_by"]


class SiteEntryTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteEntryTask
        fields = [
            "id",
            "code",
            "date",
            "order_ref",
            "client",
            "sum_text",
            "taken_by",
            "rest_text",
            "is_done",
            "done_at",
            "done_by",
        ]
        read_only_fields = fields


class ClientFeedbackSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ClientFeedback
        fields = [
            "id",
            "order_ref",
            "client",
            "phone",
            "ready_date",
            "asked_date",
            "status",
            "status_label",
            "received_date",
            "received_by",
            "text",
            "screenshot_url",
        ]
        read_only_fields = [f for f in fields if f != "text"]
