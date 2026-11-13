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
from decimal import Decimal
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
from accounting.constants import WAREHOUSE_CAT, WAREHOUSE_CAT_EMOJI, WAREHOUSE_CAT_NAME
from accounting.dto import debt_dto
from accounting.excel import build_xlsx
from accounting.models import (
    ClientFeedback,
    Debt,
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
    DebtPaySerializer,
    DebtUpdateSerializer,
    DebtWriteSerializer,
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
from ..utils import apply_period, date_range, int_param

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
        if instance.operations.exists() or instance.debts.exists():
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
        """?month=YYYY-MM (default: the next pay day), optional date_from/date_to:
        pay date, period, the advances that go into the sheet and untyped payments."""
        require_perm(request.user, VIEW_ALL)
        w = self.get_object()
        sh = SAL.salary_info(w, _month_param(request), *_period_override(request))

        def row(t):
            return {
                "id": t.id,
                "date": t.date,
                "amount": f(t.amount),
                "member": t.member.name,
                "comment": t.comment,
            }

        return Response(
            {
                "month": sh.ym,
                "pay_day": w.pay_day,
                "pay_date": sh.pay_date,
                "date_from": sh.start,
                "date_to": sh.end,
                "advance_total": f(sh.total),
                "advances": [row(t) for t in sh.rows],
                "untyped": [row(t) for t in SAL.untyped(w, sh.start, sh.end)],
            }
        )

    @action(detail=True, methods=["get"], url_path="salary/excel")
    def salary_excel(self, request, pk=None):
        require_perm(request.user, VIEW_ALL)
        return _xlsx(
            *SAL.salary_xlsx(self._worker(), _month_param(request), *_period_override(request))
        )


def _period_override(request) -> tuple[date | None, date | None]:
    """date_from + date_to (both or neither) — the accountant's own period."""
    start, end = date_range(request.query_params)
    if bool(start) != bool(end):
        raise ValidationError({"date_from": "Davr boshi va oxirini birga kiriting."})
    return start, end


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
            "member", "author", "site_user", "category", "pair", "debt"
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
        if not d["member"].has_wallet:
            raise ValidationError({"member": f"{d['member'].name}ning hamyoni yo'q."})
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
        deleted = S.delete_operation(op, by_user=request.user)
        E.operation_deleted(deleted, f"{request.user.name or request.user.phone} (sayt)")
        return Response(status=204)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        require_perm(request.user, "accounting.delete_operation", VIEW_ALL)
        op = Operation.objects.filter(pk=pk, is_deleted=True).first()
        if not op:
            raise NotFound()
        S.restore_operation(op, by_user=request.user)
        return Response(OperationSerializer(Operation.objects.get(pk=op.pk)).data)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        """Who edited / deleted / restored this row, and what changed."""
        op = Operation.objects.filter(pk=pk).first()
        if not op:
            raise NotFound()
        only = scoped_member(request)
        if only and op.member_id != only.pk:
            raise NotFound()
        return Response(
            [
                {
                    "id": c.id,
                    "action": c.action,
                    "action_label": c.get_action_display(),
                    "at": c.at,
                    "by": c.by_name,
                    "via": c.via,
                    "changes": c.changes,
                }
                for c in op.changes.all()
            ]
        )

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
                "refund": f(sm["refund"]),
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
                        "is_boss",
                        "count",
                    )
                },
                **{k: f(c[k]) for k in ("advance", "salary", "home", "other", "total", "all_time")},
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
        # owner's rule: the boss's wallet is the company cash
        cash_total = sum(r["balance"] for r in rows if r["member"]["role"] == TelegramRole.ADMIN)
        return Response(
            {"results": rows, "staff_total": f(staff_total), "cash_total": f(cash_total)}
        )


def _cat_names(codes) -> dict:
    """{code: (name, emoji)} for an order's spending categories (+ the warehouse pseudo one)."""
    names = {
        c.code: (c.name, c.emoji)
        for c in FinanceCategory.objects.filter(code__in=[c for c in codes if c != WAREHOUSE_CAT])
    }
    names[WAREHOUSE_CAT] = (WAREHOUSE_CAT_NAME, WAREHOUSE_CAT_EMOJI)
    return names


def _order_row(info, st, names: dict | None = None) -> dict:
    if names is None:
        names = _cat_names(st["cats"])
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
        "warehouse_spent": f(st.get("warehouse") or 0),
        "collected": f(st["collected"]),
        "profit": None if profit is None else f(profit),
        "spent_percent": (
            round(float(st["spent"] * 100 / info.price_uzs)) if info.price_uzs else None
        ),
        "end_date": info.end_date,
        "ready_date": info.ready_date,
        "by_category": [
            {
                "code": k,
                "amount": f(v),
                "name": names.get(k, (k, ""))[0],
                "emoji": names.get(k, (k, ""))[1],
            }
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
            from warehouse.services import allocation_refs

            booked |= allocation_refs() - set(infos)
            for ref, info in S.order_infos(booked).items():
                if info.bucket in buckets:
                    infos[ref] = info
        q = (p.get("search") or "").strip().lower()
        chosen = [i for i in infos.values() if not q or q in i.ref.lower() or q in i.client.lower()]
        stats = S.order_stats_bulk([i.ref for i in chosen])
        empty = {"spent": S.ZERO, "collected": S.ZERO, "cats": {}}
        names = _cat_names({c for st in stats.values() for c in st["cats"]})
        for info in chosen:
            refs.append(_order_row(info, stats.get(info.ref, empty), names))
        refs.sort(
            key=lambda r: (
                not r["ref"].isdigit(),
                -(int(r["ref"]) if r["ref"].isdigit() else 0),
                r["ref"],
            )
        )
        return Response({"results": refs})


# ===================================================================== debts («Qarzlar»)
class OperationModelPermissions(ModelPermissions):
    """The Operation permissions (view/add/change/delete_operation) gate the debts too:
    Debt has no permissions of its own."""

    def _queryset(self, view):
        return Operation.objects.none()


class DebtViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Owner's rule: a staff member sees / pays only the debts he wrote himself; users
    with view_all_operations see all. Paying books an expense in the chosen wallet,
    scoped like OperationViewSet.create."""

    permission_classes = [OperationModelPermissions]
    queryset = Debt.objects.none()
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        p = self.request.query_params
        status = p.get("status", "open") if self.action == "list" else "all"
        qs = S.debts_qs(status, scoped_member(self.request))
        if p.get("order_ref"):
            qs = qs.filter(order_ref=p["order_ref"])
        if self.action != "list":
            return qs
        q = (p.get("search") or "").strip()
        if q:
            qs = qs.filter(
                Q(creditor__icontains=q)
                | Q(item__icontains=q)
                | Q(order_ref__icontains=q)
                | Q(comment__icontains=q)
            )
        if status == "open":
            return qs.order_by("date", "number")
        if status == "closed":
            return qs.order_by("-closed_at", "-number")
        return qs.order_by("-date", "-number")

    def _rows(self, debts) -> list[dict]:
        infos = S.order_infos([d.order_ref for d in debts])
        return [
            debt_dto(
                d,
                infos[d.order_ref].client if d.order_ref in infos else "",
                S.debt_paid_annotated(d),
            )
            for d in debts
        ]

    def _one(self, pk) -> dict:
        d = S.debts_qs("all").get(pk=pk)
        return self._rows([d])[0]

    def _admin(self, request) -> bool:
        return request.user.has_perm(VIEW_ALL)

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(self._rows(page))

    def retrieve(self, request, *args, **kwargs):
        d = self.get_object()
        row = self._rows([d])[0]
        pays = (
            d.payments.filter(is_deleted=False)
            .select_related("member", "author", "site_user", "category", "pair", "debt")
            .prefetch_related(
                Prefetch("pair_of", queryset=Operation.objects.only("id", "number", "pair_id"))
            )
            .order_by("date", "number")
        )
        row["payments"] = OperationSerializer(pays, many=True).data
        can = S.can_modify_debt(acting_member(request), d, self._admin(request))
        row["can_change"] = can and request.user.has_perm("accounting.change_operation")
        row["can_delete"] = (
            can and not row["payments"] and request.user.has_perm("accounting.delete_operation")
        )
        return Response(row)

    def create(self, request, *args, **kwargs):
        s = DebtWriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        only = scoped_member(request)
        me = acting_member(request)
        if only and not only.has_wallet:
            raise ValidationError({"detail": "Sizning hamyoningiz yo'q."})
        debt = S.create_debt(
            creditor=d["creditor"],
            item=d["item"],
            category_code=d["category_code"],
            order_ref=d["order_ref"],
            currency=d["currency"],
            amount=d.get("amount"),
            orig_amount=d.get("orig_amount"),
            on_date=d.get("date"),
            comment=d.get("comment", ""),
            created_by=me,
            site_user=request.user,
            source="site",
            actor_admin=only is None,
        )
        return Response(self._one(debt.pk), status=201)

    def partial_update(self, request, *args, **kwargs):
        debt = self.get_object()
        s = DebtUpdateSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        only = scoped_member(request)
        if not S.can_modify_debt(acting_member(request), debt, only is None):
            raise PermissionDenied(
                "Faqat o'zingiz kiritgan, oxirgi 2 kundagi qarzni o'zgartira olasiz."
            )
        S.update_debt(debt, dict(s.validated_data), actor_admin=only is None)
        return Response(self._one(debt.pk))

    def destroy(self, request, *args, **kwargs):
        debt = self.get_object()
        only = scoped_member(request)
        if not S.can_modify_debt(acting_member(request), debt, only is None):
            raise PermissionDenied(
                "Faqat o'zingiz kiritgan, oxirgi 2 kundagi qarzni o'chira olasiz."
            )
        S.delete_debt(debt)
        return Response(status=204)

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        require_perm(request.user, "accounting.add_operation")
        debt = self.get_object()
        s = DebtPaySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        only = scoped_member(request)
        if only and d["member"].pk != only.pk:
            raise PermissionDenied("Faqat o'z hamyoningizdan to'lay olasiz.")
        if not d["member"].has_wallet:
            raise ValidationError({"member": f"{d['member'].name}ning hamyoni yo'q."})
        author = acting_member(request)
        with transaction.atomic():
            _, op = S.pay_debt(
                debt,
                payer=d["member"],
                author=author,
                amount=d.get("amount"),
                on_date=d.get("date"),
                site_user=request.user,
                source="site",
                actor_admin=only is None,
            )
        E.operation_created(op, author=author, from_site=True)
        op = Operation.objects.select_related(
            "member", "author", "site_user", "category", "pair", "debt"
        ).get(pk=op.pk)
        return Response({"debt": self._one(debt.pk), "operation": OperationSerializer(op).data})

    @action(detail=False, methods=["get"])
    def stats(self, request):
        st = S.debt_stats(scoped_member(request))
        return Response(
            {
                "open_count": st["open_count"],
                "open_uzs": str(st["open_uzs"]),
                "open_usd": str(st["open_usd"]),
            }
        )


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
        row["debts"] = [
            debt_dto(d, info.client, S.debt_paid_annotated(d))
            for d in S.debts_qs("all").filter(order_ref=info.ref).order_by("date", "number")
        ]
        row["warehouse"] = [
            {**r, "quantity": f(r["quantity"]), "total": f(r["total"])}
            for r in st["warehouse_rows"]
        ]
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
    "FIN_WARRANTY_SINCE",
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
            if k in ("FIN_BONUS_SINCE", "FIN_WARRANTY_SINCE") and value:
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
        if st == "waiting":
            # money still to collect: shown whatever the period, however old the Готов
            return qs.filter(status=st)
        qs = qs.filter(status=st) if st else qs
        return apply_period(qs, "ready_date", self.request.query_params)

    @action(detail=False, methods=["get"])
    def unpaid(self, request):
        """«Kutilmoqda»: every Готов order whose rest is not collected yet (bonus tracked
        or not), with the count and the rest per currency."""
        rows = S.unpaid_ready_orders(request.query_params.get("search", ""))
        totals: dict[str, Decimal] = {}
        for r in rows:
            totals[r["currency"]] = totals.get(r["currency"], Decimal(0)) + r["rest"]
            r["total"], r["rest"] = str(r["total"]), str(r["rest"])
        return Response(
            {
                "count": len(rows),
                "rest": {cur: str(v) for cur, v in totals.items()},
                "results": rows,
            }
        )

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
        qs = qs.filter(given=g == "1") if g in ("0", "1") else qs
        return apply_period(qs, "ready_date", self.request.query_params)

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
        qs = qs.filter(is_done=d == "1") if d in ("0", "1") else qs
        return apply_period(qs, "date", self.request.query_params)

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
        qs = qs.filter(status=st) if st else qs
        return apply_period(qs, "ready_date", self.request.query_params)


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
            S.handover_drop(op, by_user=request.user)
        else:
            boss = acting_member(request)
            if not boss or not boss.is_admin:
                raise ServiceError(
                    "Qabul qilish uchun profilingiz Telegram'da «Rahbar» rolidagi a'zoga ulangan bo'lishi kerak."
                )
            S.handover_accept(op, boss)
        return Response(OperationSerializer(Operation.objects.get(pk=op.pk)).data)


class OrderAdvanceView(APIView):
    """«Avans tasdiqlash»: advances entered at order creation, waiting for the boss.
    GET ?status=pending|accepted|rejected|all; POST {advance, action: accept|reject,
    amount_text?} — accept books the money into the boss's cash."""

    permission_classes = [ModelPermissions]
    queryset = Operation.objects.none()

    def get(self, request):
        from accounting.dto import advance_dto
        from accounting.models import OrderAdvance

        require_perm(request.user, VIEW_ALL)
        st = request.query_params.get("status") or "pending"
        qs = OrderAdvance.objects.select_related("order__client", "created_by")
        if st != "all":
            qs = qs.filter(status=st)
        return Response([advance_dto(a) for a in qs[:300]])

    def post(self, request):
        from accounting.dto import advance_dto
        from accounting.models import OrderAdvance

        require_perm(request.user, VIEW_ALL, "accounting.add_operation")
        adv = OrderAdvance.objects.filter(pk=request.data.get("advance")).first()
        if not adv:
            raise NotFound()
        boss = acting_member(request)
        if not boss or not boss.is_admin:
            raise ServiceError(
                "Tasdiqlash uchun profilingiz Telegram'da «Rahbar» rolidagi a'zoga ulangan bo'lishi kerak."
            )
        if request.data.get("action") == "reject":
            adv = S.advance_reject(adv, boss)
        else:
            text = str(request.data.get("amount_text") or "").strip() or None
            adv = S.advance_accept(adv, boss, text, by_user=request.user)
        return Response(advance_dto(adv))


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
