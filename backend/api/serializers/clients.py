from phonenumber_field.serializerfields import PhoneNumberField
from rest_framework import serializers

from call_center.constants import SolutionChoice
from call_center.models import Invoice
from call_center.services import invoice_is_editable
from client.models import Client
from metering.models import Metering

from .common import ClientShortSerializer


class ClientSerializer(serializers.ModelSerializer):
    phone = PhoneNumberField(region="UZ", read_only=True)
    orders_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Client
        fields = ["phone", "fio", "created_at", "orders_count"]
        read_only_fields = ["created_at"]


class InvoiceSerializer(serializers.ModelSerializer):
    client = ClientShortSerializer(read_only=True)
    solution_label = serializers.SerializerMethodField()
    is_editable = serializers.SerializerMethodField()
    metering_id = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id",
            "client",
            "create_date",
            "update_date",
            "desc",
            "solution",
            "solution_label",
            "is_editable",
            "metering_id",
        ]
        read_only_fields = ["create_date", "update_date", "solution"]

    def get_solution_label(self, obj):
        return SolutionChoice(obj.solution).label if obj.solution is not None else None

    def get_is_editable(self, obj):
        return invoice_is_editable(obj)

    def get_metering_id(self, obj):
        metering = getattr(obj, "metering", None)
        return metering.pk if isinstance(metering, Metering) else None


class InvoiceCreateSerializer(serializers.Serializer):
    fio = serializers.CharField(max_length=255)
    phone = PhoneNumberField(region="UZ")
    desc = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class InvoiceSolutionSerializer(serializers.Serializer):
    solution = serializers.ChoiceField(choices=SolutionChoice.choices)
