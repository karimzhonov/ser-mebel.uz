from django.db import transaction
from django.db.models import Count, F, Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response

from call_center import services as CC
from call_center.constants import SolutionChoice
from call_center.models import Invoice, InvoiceTask
from call_center.services import create_invoice, invoice_is_editable, set_invoice_solution
from client.models import Client
from core.geo import UNSET
from metering.models import Metering
from metering.services import metering_queryset_for
from oauth.models import User
from order.models import Order

from ..permissions import IsStaffUser, ModelPermissions, require_perm
from ..serializers.clients import (
    ClientSerializer,
    InvoiceCreateSerializer,
    InvoiceSerializer,
    InvoiceSolutionSerializer,
)
from ..serializers.common import LocationSetSerializer
from ..serializers.crm import (
    InvoiceTaskSerializer,
    LeadUpdateSerializer,
    NoteCreateSerializer,
    TaskCreateSerializer,
    TaskDoneSerializer,
    TaskRescheduleSerializer,
    TimelineEntrySerializer,
)
from ..serializers.metering import MeteringSerializer
from ..serializers.orders import OrderSerializer
from ..utils import apply_period, csv_values, int_param, timeseries


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
        return apply_period(qs, "created_at", self.request.query_params)

    @action(detail=True, methods=["get"])
    def related(self, request, pk=None):
        """Everything this client has gone through, newest first."""
        client = self.get_object()
        ctx = self.get_serializer_context()
        data = {"invoices": [], "meterings": [], "orders": []}
        if request.user.has_perm("call_center.view_invoice"):
            invoices = CC.with_task_annotations(
                Invoice.objects.filter(client=client)
                .select_related(
                    "client",
                    "metering__measurer",
                    "metering__manager",
                    "metering__design__user",
                    "metering__price__user",
                    "estimate",
                    "assigned_to",
                    "created_by",
                )
                .prefetch_related("metering__offer_answers")
            )
            data["invoices"] = InvoiceSerializer(
                invoices.order_by("-create_date"), many=True, context=ctx
            ).data
        if request.user.has_perm("metering.view_metering"):
            meterings = metering_queryset_for(
                request.user, Metering.objects.filter(client=client)
            ).select_related(
                "client",
                "design",
                "price",
                "order",
                "measurer",
                "created_by",
                "invoice__assigned_to",
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
                "timeline": timeseries(qs, "created_at", request.query_params),
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
        # No aggregates here: `stats` groups on this queryset.
        qs = Invoice.objects.select_related(
            "client",
            "metering__measurer",
            "metering__manager",
            "metering__design__user",
            "metering__price__user",
            "estimate",
            "assigned_to",
            "created_by",
        ).prefetch_related("metering__offer_answers")
        return apply_period(qs, "create_date", self.request.query_params)

    def get_queryset(self):
        qs = self.base_queryset()
        qs = CC.with_task_annotations(qs)
        params = self.request.query_params
        solutions = csv_values(params.get("solution"))
        if solutions:
            cond = Q()
            for value in solutions:
                if value == "new":
                    cond |= Q(solution__isnull=True)
                elif value.lstrip("-").isdigit():
                    cond |= Q(solution=int(value))
            qs = qs.filter(cond)
        return self._filter_owner(qs)

    def _filter_owner(self, qs):
        """assigned_to / source filters (shared by the list, the board and `stats`)."""
        params = self.request.query_params
        assignee = params.get("assigned_to")
        if assignee == "me":
            qs = qs.filter(assigned_to=self.request.user)
        elif assignee == "none":
            qs = qs.filter(assigned_to__isnull=True)
        elif assignee:
            qs = qs.filter(assigned_to=int_param(params, "assigned_to"))
        sources = csv_values(params.get("source"))
        if sources:
            qs = qs.filter(source__in=sources)
        return qs

    def _data(self, invoice):
        return InvoiceSerializer(invoice, context=self.get_serializer_context()).data

    def create(self, request, *args, **kwargs):
        serializer = InvoiceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invoice = create_invoice(**serializer.validated_data, author=request.user)
        return Response(self._data(invoice), status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        if not invoice_is_editable(serializer.instance):
            raise PermissionDenied("Ariza yopilgan — tahrirlab bo'lmaydi.")
        # The description is the lead's latest note: editing it appends a note.
        desc = (serializer.validated_data.pop("desc", None) or "").strip()
        with transaction.atomic():
            serializer.save()
            if desc and desc != (serializer.instance.desc or "").strip():
                CC.add_note(serializer.instance, author=self.request.user, text=desc)

    @action(detail=True, methods=["post"])
    def estimate(self, request, pk=None):
        """The lead's approximate price (to tell the client): {id} — opened at /prices/{id}."""
        from metering.price.services import create_estimate

        price = create_estimate(invoice=self.get_object(), by=request.user)
        return Response({"id": price.pk}, status=201)

    @action(detail=True, methods=["post"], serializer_class=InvoiceSolutionSerializer)
    def solution(self, request, pk=None):
        require_perm(request.user, "call_center.change_invoice")
        invoice = self.get_object()
        serializer = InvoiceSolutionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        set_invoice_solution(invoice, serializer.validated_data["solution"], author=request.user)
        # re-fetch with the task annotations: a closing answer just closed the open tasks
        fresh = CC.with_task_annotations(self.base_queryset()).get(pk=invoice.pk)
        return Response(self._data(fresh))

    @action(detail=True, methods=["post"])
    def location(self, request, pk=None):
        """Attach / clear the lead's map location: {location, address?}."""
        require_perm(request.user, "call_center.change_invoice")
        invoice = self.get_object()
        body = LocationSetSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        d = body.validated_data
        CC.set_invoice_location(
            invoice,
            point=d["point"],
            link=d["link"],
            address=d["address"] if "address" in d else UNSET,
            by=request.user,
            via="panel",
        )
        return Response({**self._data(invoice), "short": d["short"]})

    @action(detail=False, methods=["get"])
    def board(self, request):
        """Kanban columns with their cards (same filters as the list)."""
        columns = CC.lead_board(self.filter_queryset(self.get_queryset()))
        ctx = self.get_serializer_context()
        for column in columns:
            column["cards"] = InvoiceSerializer(column["cards"], many=True, context=ctx).data
        return Response({"columns": columns})

    @action(detail=False, methods=["get"])
    def assignees(self, request):
        users = CC.eligible_assignees().order_by("name", "phone")
        return Response(
            [
                {
                    "id": u.pk,
                    "name": u.name or str(u.phone),
                    "has_telegram": bool(u.telegram_id),
                }
                for u in users
            ]
        )

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        invoice = self.get_object()
        return Response(TimelineEntrySerializer(CC.lead_timeline(invoice), many=True).data)

    @action(detail=True, methods=["post"])
    def notes(self, request, pk=None):
        require_perm(request.user, "call_center.change_invoice")
        invoice = self.get_object()
        serializer = NoteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        CC.add_note(invoice, author=request.user, text=serializer.validated_data["text"])
        return Response(self._data(invoice), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"])
    def tasks(self, request, pk=None):
        invoice = self.get_object()
        if request.method == "GET":
            tasks = invoice.tasks.select_related(
                "invoice__client", "assigned_to", "created_by"
            ).order_by(F("done_at").asc(nulls_first=True), "due_at")
            return Response(InvoiceTaskSerializer(tasks, many=True).data)
        require_perm(request.user, "call_center.change_invoice")
        serializer = TaskCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        task = CC.create_task(
            invoice,
            text=data["text"],
            due_at=data["due_at"],
            by=request.user,
            assigned_to=data.get("assigned_to"),
        )
        return Response(InvoiceTaskSerializer(task).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        """Reassign the lead and/or fix its source (allowed on closed leads too)."""
        require_perm(request.user, "call_center.change_invoice")
        invoice = self.get_object()
        serializer = LeadUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        CC.update_lead(invoice, by=request.user, **serializer.validated_data)
        return Response(self._data(invoice))

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Counts per answer (the admin SolutionBanner) + the line chart."""
        qs = self.filter_queryset(self._filter_owner(self.base_queryset()))
        counts = {
            row["solution"]: row["c"]
            for row in qs.order_by().values("solution").annotate(c=Count("pk"))
        }
        return Response(
            {
                "total": qs.count(),
                "by_solution": [{"key": "new", "count": counts.get(None, 0)}]
                + [{"key": str(v), "count": counts.get(v, 0)} for v in SolutionChoice.values],
                "timeline": timeseries(qs, "create_date", request.query_params),
            }
        )


class InvoiceTaskViewSet(viewsets.GenericViewSet):
    """The CRM reminders. Anyone who may view leads sees the agenda; finishing or moving a
    task is for its assignee / creator / call-centre manager (call_center.services)."""

    permission_classes = [IsStaffUser]
    serializer_class = InvoiceTaskSerializer
    queryset = InvoiceTask.objects.select_related("invoice__client", "assigned_to", "created_by")
    pagination_class = None

    def _assignee(self, request):
        raw = request.query_params.get("assigned_to")
        if raw in (None, "", "me") or str(raw) == str(request.user.pk):
            return request.user
        require_perm(request.user, "call_center.manage_invoice")
        user = User.objects.filter(pk=int_param(request.query_params, "assigned_to")).first()
        if user is None:
            raise NotFound()
        return user

    @action(detail=False, methods=["get"])
    def agenda(self, request):
        require_perm(request.user, "call_center.view_invoice")
        agenda = CC.task_agenda(assignee=self._assignee(request), now=CC._now())
        return Response(
            {key: InvoiceTaskSerializer(rows, many=True).data for key, rows in agenda.items()}
        )

    @action(detail=False, methods=["get"])
    def summary(self, request):
        require_perm(request.user, "call_center.view_invoice")
        return Response(CC.task_counts(assignee=request.user, now=CC._now()))

    @action(detail=True, methods=["post"])
    def done(self, request, pk=None):
        require_perm(request.user, "call_center.view_invoice")
        task = self.get_object()
        serializer = TaskDoneSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        next_task = data.get("next_task")
        if next_task is not None:
            next_task = {k: v for k, v in next_task.items() if k in ("due_at", "preset", "text")}
        result = CC.complete_task(
            task,
            by=request.user,
            note=data["note"],
            outcome=data.get("outcome"),
            next_task=next_task,
        )
        body = dict(InvoiceTaskSerializer(result.task).data)
        body["next_task"] = (
            InvoiceTaskSerializer(result.next_task).data if result.next_task else None
        )
        body["closed_tasks"] = result.closed_tasks
        return Response(body)

    @action(detail=True, methods=["post"])
    def reschedule(self, request, pk=None):
        require_perm(request.user, "call_center.view_invoice")
        task = self.get_object()
        serializer = TaskRescheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        due_at = data.get("due_at") or CC.due_preset(data["preset"], CC._now())
        task = CC.reschedule_task(task, by=request.user, due_at=due_at)
        return Response(InvoiceTaskSerializer(task).data)
