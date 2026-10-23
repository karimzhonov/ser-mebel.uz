from django.db.models import Count, Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from call_center.constants import SolutionChoice
from call_center.models import Invoice
from call_center.services import create_invoice, invoice_is_editable, set_invoice_solution
from client.models import Client
from metering.models import Metering
from order.models import Order

from ..permissions import ModelPermissions, require_perm
from ..serializers.clients import (
    ClientSerializer,
    InvoiceCreateSerializer,
    InvoiceSerializer,
    InvoiceSolutionSerializer,
)
from ..serializers.metering import MeteringSerializer
from ..serializers.orders import OrderSerializer
from ..utils import apply_period, csv_values, timeseries


class ClientViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Clients are created by the call-centre/metering/order flows, never by hand, and
    are never deleted (ClientAdmin)."""

    serializer_class = ClientSerializer
    permission_classes = [ModelPermissions]
    lookup_value_regex = r"[^/]+"
    search_fields = ["fio", "phone"]
    ordering_fields = ["created_at", "fio", "orders_count"]
    ordering = ["-created_at"]
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        qs = Client.objects.annotate(orders_count=Count("order", distinct=True))
        return apply_period(qs, "created_at", self.request.query_params.get("period"))

    @action(detail=True, methods=["get"])
    def related(self, request, pk=None):
        """Everything this client has gone through, newest first."""
        client = self.get_object()
        ctx = self.get_serializer_context()
        data = {"invoices": [], "meterings": [], "orders": []}
        if request.user.has_perm("call_center.view_invoice"):
            invoices = Invoice.objects.filter(client=client).select_related("client")
            data["invoices"] = InvoiceSerializer(
                invoices.order_by("-create_date"), many=True, context=ctx
            ).data
        if request.user.has_perm("metering.view_metering"):
            meterings = Metering.objects.filter(client=client).select_related(
                "client", "design", "price", "order"
            )
            data["meterings"] = MeteringSerializer(
                meterings.order_by("-create_date"), many=True, context=ctx
            ).data
        if request.user.has_perm("order.view_order"):
            orders = Order.objects.filter(client=client).select_related("client", "factory")
            data["orders"] = OrderSerializer(
                orders.order_by("-order_number"), many=True, context=ctx
            ).data
        return Response(data)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        qs = self.filter_queryset(self.get_queryset())
        top = qs.order_by("-orders_count")[:10]
        return Response(
            {
                "total": qs.count(),
                "top": ClientSerializer(top, many=True).data,
                "timeline": timeseries(qs, "created_at", request.query_params.get("period")),
            }
        )


class InvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = InvoiceSerializer
    permission_classes = [ModelPermissions]
    search_fields = ["client__fio", "client__phone", "desc"]
    ordering_fields = ["create_date", "update_date"]
    ordering = ["-create_date"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def base_queryset(self):
        qs = Invoice.objects.select_related("client", "metering")
        return apply_period(qs, "create_date", self.request.query_params.get("period"))

    def get_queryset(self):
        qs = self.base_queryset()
        solutions = csv_values(self.request.query_params.get("solution"))
        if solutions:
            cond = Q()
            for value in solutions:
                if value == "new":
                    cond |= Q(solution__isnull=True)
                elif value.lstrip("-").isdigit():
                    cond |= Q(solution=int(value))
            qs = qs.filter(cond)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = InvoiceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invoice = create_invoice(**serializer.validated_data)
        return Response(
            InvoiceSerializer(invoice, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    def perform_update(self, serializer):
        if not invoice_is_editable(serializer.instance):
            raise PermissionDenied("Заявка ёпилган — таҳрирлаб бўлмайди.")
        serializer.save()

    @action(detail=True, methods=["post"], serializer_class=InvoiceSolutionSerializer)
    def solution(self, request, pk=None):
        require_perm(request.user, "call_center.change_invoice")
        invoice = self.get_object()
        serializer = InvoiceSolutionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        set_invoice_solution(invoice, serializer.validated_data["solution"])
        return Response(InvoiceSerializer(invoice, context=self.get_serializer_context()).data)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Counts per answer (the admin SolutionBanner) + the line chart."""
        qs = self.filter_queryset(self.base_queryset())
        counts = {
            row["solution"]: row["c"]
            for row in qs.order_by().values("solution").annotate(c=Count("pk"))
        }
        return Response(
            {
                "total": qs.count(),
                "by_solution": [{"key": "new", "count": counts.get(None, 0)}]
                + [{"key": str(v), "count": counts.get(v, 0)} for v in SolutionChoice.values],
                "timeline": timeseries(qs, "create_date", request.query_params.get("period")),
            }
        )
