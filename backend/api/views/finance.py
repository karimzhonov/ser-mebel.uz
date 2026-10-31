"""Moliya (finance) API — the site side of the finance Telegram bot.

Every write goes through accounting.services (the same functions the bot's internal API
calls); Telegram side effects are queued as events (accounting.events -> core.bot_notify),
so booking on the site posts to the channel and tells the wallet owner exactly like
booking in the bot.

Row scoping: without accounting.view_all_operations a user only sees the wallet of
the Telegram member linked to their account.
"""

from __future__ import annotations

import logging
from datetime import date
from urllib.parse import quote

from constance import config
from django.conf import settings
from django.db import transaction
from django.db.models import Max, Prefetch, Q, Sum
from django.http import HttpResponse
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounting import events as E
from accounting import salary as SAL
from accounting import services as S
from accounting.excel import build_xlsx
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
from accounting.schedule import sync_periodic_tasks
from accounting.text import month_bounds, today
from core.bot_notify import fetch_file
from core.exceptions import ServiceError
from oauth.models import TelegramMember, TelegramRole

from ..permissions import IsSuperUser, ModelPermissions, is_staff, require_perm
from ..serializers.finance import (
    ClientFeedbackSerializer,
    FinanceCarSerializer,
    FinanceCategorySerializer,
    ManualOrderSerializer,
    MoneyRequestSerializer,
    MonthReportSerializer,
    OperationSerializer,
    OperationWriteSerializer,
    OrderBonusSerializer,
    SiteEntryTaskSerializer,
    TelegramMemberSerializer,
    TransferSerializer,
    WarrantyLetterSerializer,
    WorkerSerializer,
)
from ..utils import date_range, int_param

log = logging.getLogger("finance.api")

VIEW_ALL = "accounting.view_all_operations"


def f(v) -> float:
    return round(float(v or 0), 2)


def acting_member(request) -> TelegramMember | None:
    return getattr(request.user, "telegram_member", None)


def scoped_member(request) -> TelegramMember | None:
    """None = may see everything; otherwise the only wallet this user may see."""
    if request.user.has_perm(VIEW_ALL):
        return None
    m = acting_member(request)
    if not m:
        raise PermissionDenied(
            "Profilingiz Telegram a'zoga ulanmagan — faqat o'z hamyoningizni ko'ra olasiz."
        )
    return m


# ===================================================================== catalogs
class _CatalogViewSet(viewsets.ModelViewSet):
    permission_classes = [ModelPermissions]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]


class FinanceCategoryViewSet(_CatalogViewSet):
    queryset = FinanceCategory.objects.all()
    serializer_class = FinanceCategorySerializer

    def perform_destroy(self, instance):
        if instance.operations.exists():
            raise ServiceError(
                "Bu kategoriyada amallar bor — o'chirish o'rniga «Faol emas» qiling."
            )
        instance.delete()


class WorkerViewSet(_CatalogViewSet):
    """«Ishchilar» + «Oylik chiqarish»: each worker's Excel template and the sheet
    with their advances filled in (accounting/salary.py)."""

    queryset = Worker.objects.defer("salary_template")
    serializer_class = WorkerSerializer

    def _worker(self):
        return Worker.objects.get(pk=self.get_object().pk)  # with the template bytes

    @action(
        detail=True,
        methods=["get", "post", "delete"],
        parser_classes=[MultiPartParser, FormParser],
    )
    def template(self, request, pk=None):
        """GET = download (a starter one when none is uploaded); POST file = upload;
        DELETE = remove."""
        w = self._worker()
        if request.method == "GET":
            require_perm(request.user, VIEW_ALL)
            return _xlsx(*SAL.template_file(w))
        require_perm(request.user, "accounting.change_worker")
        if request.method == "DELETE":
            SAL.remove_template(w)
        else:
            f = request.FILES.get("file")
            if not f:
                raise ServiceError("Faylni tanlang.")
            if f.size > SAL.MAX_TEMPLATE:
                raise ServiceError("Fayl juda katta (5 MB gacha).")
            SAL.save_template(w, f.name, f.read())
        w.salary_template = None
        return Response(WorkerSerializer(w).data)

    @action(detail=True, methods=["get"])
    def salary(self, request, pk=None):
        """?month=YYYY-MM (default: the next pay day): pay date, period and advances."""
        require_perm(request.user, VIEW_ALL)
        w = self.get_object()
        sh = SAL.salary_info(w, _month_param(request))
        return Response(
            {
                "month": sh.ym,
                "pay_date": sh.pay_date,
                "date_from": sh.start,
                "date_to": sh.end,
                "advance_total": f(sh.total),
                "advances": [
                    {
                        "id": t.id,
                        "date": t.date,
                        "amount": f(t.amount),
                        "member": t.member.name,
                        "comment": t.comment,
                    }
                    for t in sh.rows
                ],
            }
        )

    @action(detail=True, methods=["get"], url_path="salary/excel")
    def salary_excel(self, request, pk=None):
        require_perm(request.user, VIEW_ALL)
        return _xlsx(*SAL.salary_xlsx(self._worker(), _month_param(request)))


def _month_param(request) -> str | None:
    ym = str(request.query_params.get("month") or "").strip()
    if not ym:
        return None
    try:
        y, m = (int(x) for x in ym.split("-"))
        date(y, m, 1)
    except ValueError as e:
        raise ValidationError({"month": "YYYY-MM"}) from e
    return f"{y:04d}-{m:02d}"


def _xlsx(content: bytes, name: str) -> HttpResponse:
    resp = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    ascii_name = name.encode("ascii", "ignore").decode() or "oylik.xlsx"
    resp["Content-Disposition"] = (
        f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
    )
    return resp


class FinanceCarViewSet(_CatalogViewSet):
    queryset = FinanceCar.objects.all()
    serializer_class = FinanceCarSerializer


class ManualOrderViewSet(_CatalogViewSet):
    queryset = ManualOrder.objects.all()
    serializer_class = ManualOrderSerializer
    search_fields = ["ref", "client"]


class TelegramMemberViewSet(viewsets.ModelViewSet):
    """Telegram roles: who uses the finance bot and as what (admin/staff/pending/blocked
    + duties). Separate from site permissions."""

    queryset = TelegramMember.objects.select_related("user").order_by("role", "name")
    serializer_class = TelegramMemberSerializer
    permission_classes = [ModelPermissions]
    pagination_class = None
    search_fields = ["name", "username"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        if self.action == "destroy":
            return [IsSuperUser()]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        role = self.request.query_params.get("role")
        return qs.filter(role=role) if role else qs

    def perform_update(self, serializer):
        old_role = serializer.instance.role
        m = serializer.save()
        if old_role == TelegramRole.PENDING and m.role == TelegramRole.STAFF:
            E.member_approved(m)

    def perform_destroy(self, instance):
        if instance.operations.exists():
            raise ServiceError("Bu a'zoning amallari bor — o'chirish o'rniga «Bloklangan» qiling.")
        instance.delete()


# ===================================================================== operations
class OperationViewSet(viewsets.ModelViewSet):
    permission_classes = [ModelPermissions]
    serializer_class = OperationSerializer
    search_fields = ["comment", "worker", "order_ref", "member__name", "category__name"]
    ordering_fields = ["date", "number", "amount"]
    ordering = ["-date", "-number"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = Operation.objects.select_related(
            "member", "author", "site_user", "category", "pair"
        ).prefetch_related(
            Prefetch("pair_of", queryset=Operation.objects.only("id", "number", "pair_id"))
        )
        p = self.request.query_params
        only = scoped_member(self.request)
        if only:
            qs = qs.filter(member=only)
        if p.get("deleted") == "1":
            qs = qs.filter(is_deleted=True)
        elif p.get("deleted") != "all":
            qs = qs.filter(is_deleted=False)
        start, end = date_range(p)
        if start:
            qs = qs.filter(date__gte=start)
        if end:
            qs = qs.filter(date__lte=end)
        for name in ("member",):
            v = int_param(p, name)
            if v is not None:
                qs = qs.filter(member_id=v)
        if p.get("kind") in ("income", "expense"):
            qs = qs.filter(kind=p["kind"])
        if p.get("category"):
            qs = qs.filter(category__code__in=p["category"].split(","))
        if p.get("order_ref"):
            qs = qs.filter(order_ref=p["order_ref"])
        if p.get("source"):
            qs = qs.filter(source=p["source"])
        return qs

    def _write(self, partial=False) -> dict:
        s = OperationWriteSerializer(data=self.request.data, partial=partial)
        s.is_valid(raise_exception=True)
        return dict(s.validated_data)

    def create(self, request, *args, **kwargs):
        d = self._write()
        for k in ("member", "kind", "category_code"):
            if k not in d:
                raise ValidationError({k: "Majburiy maydon."})
        only = scoped_member(request)
        if only and d["member"].pk != only.pk:
            raise PermissionDenied("Faqat o'z hamyoningizga yozishingiz mumkin.")
        cur = d.get("currency") or "UZS"
        amount = d.get("amount")
        if cur == "USD":
            if not d.get("orig_amount") or not d.get("rate"):
                raise ValidationError({"orig_amount": "Dollar summasi va kursi kerak."})
            amount = round(d["orig_amount"] * d["rate"])
        if not amount:
            raise ValidationError({"amount": "Summa kiriting."})
        author = acting_member(request)
        with transaction.atomic():
            op = S.create_operation(
                member=d["member"],
                author=author,
                kind=d["kind"],
                amount=amount,
                category_code=d["category_code"],
                currency=cur,
                orig_amount=d.get("orig_amount"),
                rate=d.get("rate"),
                order_ref=d.get("order_ref"),
                comment=d.get("comment", ""),
                worker=d.get("worker", ""),
                pay_type=d.get("pay_type", ""),
                source="site",
                site_user=request.user,
                on_date=d.get("date"),
                actor_admin=only is None,
            )
            S.boss_hand_out(op, author)
        E.operation_created(op, author=author, from_site=True)
        return Response(OperationSerializer(op).data, status=201)

    def partial_update(self, request, *args, **kwargs):
        op = self.get_object()
        d = self._write(partial=True)
        only = scoped_member(request)
        if not S.can_modify(only, op, admin=only is None, edit=True):
            raise PermissionDenied(
                "Faqat o'zingiz kiritgan, oxirgi 2 kundagi yozuvni o'zgartira olasiz "
                "(mijoz puli va o'tkazmalarni faqat rahbar o'zgartiradi)."
            )
        if only and "member" in d and d["member"].pk != only.pk:
            raise PermissionDenied("Faqat o'z hamyoningizga yozishingiz mumkin.")
        before = {
            "kind_label": op.get_kind_display(),
            "amount": str(op.amount),
            "category_name": op.category.name,
        }
        op = S.update_operation(op, d, site_user=request.user, actor_admin=only is None)
        E.operation_edited(op, before, f"{request.user.name or request.user.phone} (sayt)")
        return Response(OperationSerializer(Operation.objects.get(pk=op.pk)).data)

    def destroy(self, request, *args, **kwargs):
        op = self.get_object()
        only = scoped_member(request)
        if not S.can_modify(only, op, admin=only is None):
            raise PermissionDenied(
                "Faqat o'zingiz kiritgan, oxirgi 2 kundagi yozuvni o'chira olasiz."
            )
        deleted = S.delete_operation(op)
        E.operation_deleted(deleted, f"{request.user.name or request.user.phone} (sayt)")
        return Response(status=204)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        require_perm(request.user, "accounting.delete_operation", VIEW_ALL)
        op = Operation.objects.filter(pk=pk, is_deleted=True).first()
        if not op:
            raise NotFound()
        S.restore_operation(op)
        return Response(OperationSerializer(Operation.objects.get(pk=op.pk)).data)

    @action(detail=True, methods=["get"])
    def receipt(self, request, pk=None):
        op = self.get_object()
        if not op.receipt_file_id:
            raise NotFound("Chek yo'q.")
        got = fetch_file(op.receipt_file_id)
        if not got:
            raise NotFound("Chekni Telegram'dan olib bo'lmadi.")
        resp = HttpResponse(got[0], content_type=got[1])
        resp["Cache-Control"] = "private, max-age=86400"
        return resp

    @action(detail=False, methods=["post"])
    def transfer(self, request):
        require_perm(request.user, "accounting.add_operation")
        s = TransferSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        only = scoped_member(request)
        if only and d["sender"].pk != only.pk:
            raise PermissionDenied("Faqat o'z hamyoningizdan bera olasiz.")
        author = acting_member(request)
        out, inc = S.create_transfer(
            sender=d["sender"],
            receiver=d["receiver"],
            amount=d["amount"],
            comment=d["comment"],
            author=author,
            source="site",
            site_user=request.user,
        )
        E.transfer_created(out, inc, author)
        return Response(OperationSerializer([out, inc], many=True).data, status=201)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Totals for the current filter (what the list shows)."""
        qs = self.filter_queryset(self.get_queryset())
        inc = exp = 0
        for kind, amount in qs.values_list("kind", "amount"):
            if kind == "income":
                inc += amount
            else:
                exp += amount
        return Response({"income": f(inc), "expense": f(exp), "count": qs.count()})


# ===================================================================== dashboard / wallets / orders
def _period(request) -> tuple[date, date]:
    start, end = date_range(request.query_params)
    if not start and not end:
        start, end = month_bounds(today().strftime("%Y-%m"))
    return start or date(2000, 1, 1), end or today()


def _items(items):
    return [
        {
            "code": i["code"],
            "name": i["name"],
            "emoji": i["emoji"],
            "color": i["color"],
            "amount": f(i["sum"]),
            "count": i["n"],
        }
        for i in items
    ]


class FinanceSummaryView(APIView):
    """«Xulosa»: cards, by category, salaries, 12 months — for a period (and a member)."""

    permission_classes = [ModelPermissions]
    queryset = Operation.objects.none()

    def get(self, request):
        start, end = _period(request)
        member = scoped_member(request)
        mid = int_param(request.query_params, "member")
        if mid and not member:
            member = TelegramMember.objects.filter(pk=mid).first()
        sm = S.summary(start, end, member)
        months = S.months_series(member, 12)
        return Response(
            {
                "date_from": start,
                "date_to": end,
                "member": TelegramMemberSerializer(member).data if member else None,
                "expense": f(sm["expense"]),
                "income": f(sm["income"]),
                "balance": f(sm["balance"]),
                "given_to_staff": f(sm["given_to_staff"]),
                "boss_personal": f(sm["boss_personal"]),
                "home": f(sm["home"]),
                "transfers": f(sm["transfers"]),
                "count": sm["count"],
                "expense_by_category": _items(sm["expense_by_category"]),
                "income_by_category": _items(sm["income_by_category"]),
                "salary_by_worker": [
                    {"name": n, "amount": f(v)} for n, v in sm["salary_by_worker"]
                ],
                "months": [
                    {
                        "month": x["month"],
                        "label": x["label"],
                        "income": f(x["income"]),
                        "expense": f(x["expense"]),
                    }
                    for x in months
                ],
                "wallet_balance": f(S.balance(member)) if member else None,
                "usd_rate": f(S.usd_rate()),
            }
        )


class WorkerCardView(APIView):
    """«👷 Ishchi kartasi»: the worker list for a period and, with ?worker=, one worker's
    advances / salaries, who paid them and every payment. Company-wide pay, so only
    for those who see every wallet."""

    permission_classes = [ModelPermissions]
    queryset = Operation.objects.none()

    def get(self, request):
        require_perm(request.user, VIEW_ALL)
        start, end = _period(request)
        workers = [{**w, "total": f(w["total"])} for w in S.worker_list(start, end)]
        name = str(request.query_params.get("worker") or "").strip()
        card = None
        if name:
            c = S.worker_card(name, start, end)
            card = {
                **{
                    k: c[k]
                    for k in (
                        "worker_id",
                        "pay_day",
                        "template_name",
                        "name",
                        "group",
                        "position",
                        "in_catalog",
                        "count",
                    )
                },
                **{k: f(c[k]) for k in ("advance", "salary", "other", "total", "all_time")},
                "last_date": c["last_date"],
                "by_giver": [
                    {"name": g["name"], "amount": f(g["sum"]), "count": g["count"]}
                    for g in c["by_giver"]
                ],
                "rows": [
                    {
                        "id": t.id,
                        "number": t.number,
                        "date": t.date,
                        "time": t.time.strftime("%H:%M") if t.time else "",
                        "amount": f(t.amount),
                        "currency": t.currency,
                        "orig_amount": f(t.orig_amount) if t.orig_amount is not None else None,
                        "member": t.member.name,
                        "comment": t.comment,
                        "pay_type": t.pay_type,
                    }
                    for t in c["rows"]
                ],
            }
        return Response({"date_from": start, "date_to": end, "workers": workers, "card": card})


class WalletsView(APIView):
    permission_classes = [ModelPermissions]
    queryset = Operation.objects.none()

    def get(self, request):
        only = scoped_member(request)
        start, end = _period(request)
        bal = S.balances()
        rep_month = S.month_for_report()
        reported = set(
            MonthReport.objects.filter(month=rep_month).values_list("member_id", flat=True)
        )
        rows = []
        members = [only] if only else S.wallets()
        # the «Xulosa» wallet table of code.txt: given = every kirim, spent = chiqim
        # without transfers to colleagues
        per = {
            r["member_id"]: r
            for r in Operation.objects.filter(
                is_deleted=False, date__gte=start, date__lte=end, member__in=members
            )
            .values("member_id")
            .annotate(
                inc=Sum("amount", filter=Q(kind="income")),
                exp=Sum("amount", filter=Q(kind="expense") & ~Q(category__code="otkazma")),
            )
        }
        last = dict(
            Operation.objects.filter(is_deleted=False, member__in=members)
            .values("member_id")
            .annotate(d=Max("date"))
            .values_list("member_id", "d")
        )
        for m in members:
            p = per.get(m.id, {})
            rows.append(
                {
                    "member": TelegramMemberSerializer(m).data,
                    "balance": f(bal.get(m.id, 0)),
                    "period_income": f(p.get("inc")),
                    "period_expense": f(p.get("exp")),
                    "last_day": last.get(m.id),
                    "report_month": rep_month,
                    "report_submitted": m.id in reported,
                }
            )
        staff_total = sum(r["balance"] for r in rows if r["member"]["role"] == TelegramRole.STAFF)
        return Response({"results": rows, "staff_total": f(staff_total)})


def _order_row(info, st) -> dict:
    profit = info.price_uzs - st["spent"] if info.price_uzs else None
    return {
        "ref": info.ref,
        "client": info.client,
        "phone": info.phone,
        "bucket": info.bucket,
        "status_label": info.status_label,
        "order_id": info.order.id if info.order else None,
        "manual": bool(info.manual),
        "total": f(info.total),
        "currency": info.currency,
        "paid": None if info.paid is None else f(info.paid),
        "rest": None if info.rest is None else f(info.rest),
        "price_uzs": f(info.price_uzs),
        "spent": f(st["spent"]),
        "collected": f(st["collected"]),
        "profit": None if profit is None else f(profit),
        "spent_percent": (
            round(float(st["spent"] * 100 / info.price_uzs)) if info.price_uzs else None
        ),
        "end_date": info.end_date,
        "ready_date": info.ready_date,
        "by_category": [
            {"code": k, "amount": f(v)}
            for k, v in sorted(st["cats"].items(), key=lambda kv: -kv[1])
        ],
    }


class FinanceOrdersView(APIView):
    """Money per order: spent (bot/site expenses), collected, contract, profit."""

    permission_classes = [ModelPermissions]
    queryset = Operation.objects.none()

    def get(self, request):
        require_perm(request.user, VIEW_ALL)
        p = request.query_params
        buckets = (p.get("bucket") or "jarayonda,yangi,kutish,yakun").split(",")
        refs = []
        infos = {i.ref: i for i in S.open_orders(buckets)}
        if p.get("with_ops") == "1" or "tugadi" in buckets:
            booked = set(
                Operation.objects.filter(is_deleted=False)
                .exclude(order_ref="")
                .values_list("order_ref", flat=True)
                .distinct()
            ) - set(infos)
            for ref, info in S.order_infos(booked).items():
                if info.bucket in buckets:
                    infos[ref] = info
        q = (p.get("search") or "").strip().lower()
        chosen = [i for i in infos.values() if not q or q in i.ref.lower() or q in i.client.lower()]
        stats = S.order_stats_bulk([i.ref for i in chosen])
        empty = {"spent": S.ZERO, "collected": S.ZERO, "cats": {}}
        for info in chosen:
            refs.append(_order_row(info, stats.get(info.ref, empty)))
        refs.sort(
            key=lambda r: (
                not r["ref"].isdigit(),
                -(int(r["ref"]) if r["ref"].isdigit() else 0),
                r["ref"],
            )
        )
        return Response({"results": refs})


class FinanceOrderDetailView(APIView):
    permission_classes = [ModelPermissions]
    queryset = Operation.objects.none()

    def get(self, request, ref):
        require_perm(request.user, VIEW_ALL)
        info = S.order_info(ref)
        if not info:
            raise NotFound("Buyurtma topilmadi.")
        st = S.order_stats(info.ref)
        row = _order_row(info, st)
        row["operations"] = OperationSerializer(st["rows"], many=True).data
        bn = OrderBonus.objects.filter(order_ref=info.ref).first()
        row["bonus"] = OrderBonusSerializer(bn).data if bn else None
        return Response(row)


class FinanceOrderOptionsView(APIView):
    """Order picker for the operation form (same lists as the bot keyboards)."""

    permission_classes = [ModelPermissions]
    queryset = Operation.objects.none()

    def get(self, request):
        buckets = (request.query_params.get("bucket") or "jarayonda,yangi,kutish,yakun").split(",")
        return Response(
            [{"ref": i.ref, "client": i.client, "bucket": i.bucket} for i in S.open_orders(buckets)]
        )


class ChecksView(APIView):
    permission_classes = [ModelPermissions]
    queryset = Operation.objects.none()

    def get(self, request):
        require_perm(request.user, VIEW_ALL)
        return Response(S.checks())


class ExportView(APIView):
    permission_classes = [ModelPermissions]
    queryset = Operation.objects.none()

    def get(self, request):
        require_perm(request.user, VIEW_ALL)
        start, end = _period(request)
        content = build_xlsx(start, end)
        resp = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp["Content-Disposition"] = (
            f'attachment; filename="SerMebel_{start:%Y-%m-%d}_{end:%Y-%m-%d}.xlsx"'
        )
        return resp


SETTING_KEYS = [
    "FIN_REMINDER_HOUR",
    "FIN_ADMIN_REPORT_HOUR",
    "FIN_MONTH_END_DAYS",
    "FIN_WARN_PERCENT",
    "FIN_USD_RATE",
    "FIN_CHANNEL_ID",
    "FIN_READY_DAYS",
    "FIN_BONUS_SINCE",
]


SETTING_RANGES = {
    "FIN_REMINDER_HOUR": (0, 23),
    "FIN_ADMIN_REPORT_HOUR": (0, 23),
    "FIN_MONTH_END_DAYS": (1, 15),
    "FIN_WARN_PERCENT": (1, 100),
    "FIN_USD_RATE": (0, 1_000_000),
    "FIN_READY_DAYS": (1, 365),
}


class FinanceSettingsView(APIView):
    permission_classes = [ModelPermissions]
    queryset = FinanceCategory.objects.none()

    def get(self, request):
        data = {k: getattr(config, k) for k in SETTING_KEYS}
        data["usd_rate_effective"] = f(S.usd_rate())
        return Response(data)

    def patch(self, request):
        require_perm(request.user, "accounting.change_financecategory")
        types = {k: type(settings.CONSTANCE_CONFIG[k][0]) for k in SETTING_KEYS}
        clean = {}
        for k, v in request.data.items():
            if k not in SETTING_KEYS:
                raise ValidationError({k: "Noma'lum sozlama."})
            try:
                value = types[k](v if v is not None else types[k]())
            except (TypeError, ValueError):
                raise ValidationError({k: "Noto'g'ri qiymat."})
            lo_hi = SETTING_RANGES.get(k)
            if lo_hi and not lo_hi[0] <= value <= lo_hi[1]:
                raise ValidationError({k: f"{lo_hi[0]} dan {lo_hi[1]} gacha bo'lishi kerak."})
            if k == "FIN_BONUS_SINCE" and value:
                try:
                    date.fromisoformat(value)
                except ValueError:
                    raise ValidationError({k: "Sana YYYY-MM-DD formatida bo'lishi kerak."})
            clean[k] = value
        for k, value in clean.items():
            setattr(config, k, value)
        if clean.keys() & {"FIN_REMINDER_HOUR", "FIN_ADMIN_REPORT_HOUR"}:
            sync_periodic_tasks()
        return self.get(request)


# ===================================================================== reports, requests, bonus & tasks
class MonthReportViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = MonthReportSerializer
    permission_classes = [ModelPermissions]

    def get_queryset(self):
        qs = MonthReport.objects.select_related("member")
        only = scoped_member(self.request)
        if only:
            qs = qs.filter(member=only)
        if self.request.query_params.get("month"):
            qs = qs.filter(month=self.request.query_params["month"])
        return qs

    @action(detail=False, methods=["get"])
    def preview(self, request):
        """What «📤 Oylik hisob» would submit for a member and month."""
        only = scoped_member(request)
        mid = int_param(request.query_params, "member")
        member = only or TelegramMember.objects.filter(pk=mid).first()
        if not member:
            raise ValidationError({"member": "Xodimni tanlang."})
        ym = request.query_params.get("month") or S.month_for_report()
        sm = S.month_summary(member, ym)
        return Response(
            {
                k: (f(v) if k in ("opening", "income", "expense", "closing") else v)
                for k, v in sm.items()
            }
        )

    @action(detail=False, methods=["post"])
    def submit(self, request):
        require_perm(request.user, "accounting.add_monthreport")
        only = scoped_member(request)
        member = only or TelegramMember.objects.filter(pk=request.data.get("member")).first()
        if not member:
            raise ValidationError({"member": "Xodimni tanlang."})
        rep = S.submit_month(
            member, request.data.get("month") or S.month_for_report(), request.data.get("note", "")
        )
        return Response(MonthReportSerializer(rep).data, status=201)


class MoneyRequestViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = MoneyRequestSerializer
    permission_classes = [ModelPermissions]

    def get_queryset(self):
        qs = MoneyRequest.objects.select_related("member", "answered_by", "operation")
        only = scoped_member(self.request)
        if only:
            qs = qs.filter(member=only)
        if self.request.query_params.get("status"):
            qs = qs.filter(status=self.request.query_params["status"])
        return qs

    def _req(self, pk):
        req = self.get_queryset().filter(pk=pk).first()
        if not req:
            raise NotFound()
        return req

    @action(detail=True, methods=["post"])
    def give(self, request, pk=None):
        require_perm(request.user, "accounting.change_moneyrequest", VIEW_ALL)
        req = self._req(pk)
        m = S.request_amount(req, request.data.get("amount"))
        op = S.give_request(req, acting_member(request), m, site_user=request.user)
        req.refresh_from_db()
        # an answer given on the site is not announced in the channel (post_to_channel=false)
        E.request_answered(
            req, "given", f"{request.user.name or request.user.phone} (sayt)", True, op
        )
        return Response(MoneyRequestSerializer(req).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        require_perm(request.user, "accounting.change_moneyrequest", VIEW_ALL)
        req = S.reject_request(self._req(pk), acting_member(request))
        E.request_answered(
            req, "rejected", f"{request.user.name or request.user.phone} (sayt)", True
        )
        return Response(MoneyRequestSerializer(req).data)


class OrderBonusViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    queryset = OrderBonus.objects.all()
    serializer_class = OrderBonusSerializer
    permission_classes = [ModelPermissions]
    search_fields = ["order_ref", "client"]
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        st = self.request.query_params.get("status")
        return qs.filter(status=st) if st else qs

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        """Close as fully paid (when the rest is 0 on the site), like «✅ Zakazni yopish»."""
        require_perm(request.user, "accounting.change_orderbonus")
        bn = self.get_object()
        if bn.status != "waiting":
            raise ServiceError("Bu bonus allaqachon yopilgan.")
        ms = S.money_state(bn)
        # Same as «✅ Zakazni yopish» in the bot: only when the client owes nothing.
        if ms["rest"] > S.bonus_tolerance(bn.currency):
            raise ServiceError(
                "Qoldiq hali 0 emas — zakazni faqat qoldiq 0 bo'lganda yopish mumkin."
            )
        bn = S.bonus_finish(bn, f"Yopdi: {request.user.name or request.user.phone} (sayt)")
        E.bonus_done(bn)
        return Response(OrderBonusSerializer(bn).data)


class WarrantyLetterViewSet(
    mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    queryset = WarrantyLetter.objects.all()
    serializer_class = WarrantyLetterSerializer
    permission_classes = [ModelPermissions]
    search_fields = ["order_ref", "client"]
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        g = self.request.query_params.get("given")
        return qs.filter(given=g == "1") if g in ("0", "1") else qs

    @action(detail=True, methods=["post"])
    def give(self, request, pk=None):
        require_perm(request.user, "accounting.change_warrantyletter")
        w = S.warranty_give(
            self.get_object().order_ref, request.user.name or str(request.user.phone)
        )
        return Response(WarrantyLetterSerializer(w).data)


class SiteEntryTaskViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = SiteEntryTask.objects.all()
    serializer_class = SiteEntryTaskSerializer
    permission_classes = [ModelPermissions]

    def get_queryset(self):
        qs = super().get_queryset()
        d = self.request.query_params.get("done")
        return qs.filter(is_done=d == "1") if d in ("0", "1") else qs

    @action(detail=True, methods=["post"])
    def done(self, request, pk=None):
        require_perm(request.user, "accounting.change_siteentrytask")
        task = S.site_entry_done(self.get_object(), request.user.name or str(request.user.phone))
        E.site_entry_done(task, f"{task.done_by} (sayt)")
        return Response(SiteEntryTaskSerializer(task).data)


class ClientFeedbackViewSet(
    mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    queryset = ClientFeedback.objects.all()
    serializer_class = ClientFeedbackSerializer
    permission_classes = [ModelPermissions]
    search_fields = ["order_ref", "client"]
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        st = self.request.query_params.get("status")
        return qs.filter(status=st) if st else qs


class HandoverView(APIView):
    """/topshiruv on the site: cash a worker collected and has not handed over yet."""

    permission_classes = [ModelPermissions]
    queryset = Operation.objects.none()

    def get(self, request):
        require_perm(request.user, VIEW_ALL)
        return Response(OperationSerializer(S.handover_pending(), many=True).data)

    def post(self, request):
        require_perm(request.user, VIEW_ALL, "accounting.change_operation")
        op = Operation.objects.filter(pk=request.data.get("operation")).first()
        if not op:
            raise NotFound()
        if request.data.get("action") == "drop":
            S.handover_drop(op)
        else:
            boss = acting_member(request)
            if not boss or not boss.is_admin:
                raise ServiceError(
                    "Qabul qilish uchun profilingiz Telegram'da «Rahbar» rolidagi a'zoga ulangan bo'lishi kerak."
                )
            S.handover_accept(op, boss)
        return Response(OperationSerializer(Operation.objects.get(pk=op.pk)).data)


class MeFinanceView(APIView):
    """Which Telegram member (if any) the logged-in user is — the SPA uses it to
    pre-select «my wallet»."""

    def get(self, request):
        if not is_staff(request.user):
            raise PermissionDenied()
        m = acting_member(request)
        return Response(
            {
                "member": TelegramMemberSerializer(m).data if m else None,
                "view_all": request.user.has_perm(VIEW_ALL),
                "balance": f(S.balance(m)) if m else None,
            }
        )
