"""Bot API - finance (Moliya). Replaces the old in-process Telegram router.

Views stay thin: read the signed actor, enforce the role, call accounting.services, queue
the events (accounting.events) and return DTOs. No Telegram wording here.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from constance import config
from django.http import HttpResponse
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response

from accounting import events as E
from accounting import followup
from accounting import services as S
from accounting.excel import member_month_xlsx, month_xlsx
from accounting.images import card_values, report_card_png
from accounting.models import (
    ClientFeedback,
    FinanceCar,
    ManualOrder,
    MoneyRequest,
    Operation,
    OrderBonus,
    SiteEntryTask,
    WarrantyLetter,
    Worker,
)
from accounting.text import (
    cur_month,
    days_between,
    money,
    month_bounds,
    num,
    parse_money,
    parse_quick,
    today,
)
from core.exceptions import ServiceError
from oauth.models import TelegramMember, TelegramRole

from ...serializers import bot as D
from .base import BotAPIView

_YM = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
BUCKETS = {"yangi", "jarayonda", "kutish", "yakun", "tugadi"}
DUTIES = {"is_site_entry", "is_feedback", "is_bonus_receiver", "is_deadline_receiver"}


def _dec(value, field: str = "summa") -> Decimal:
    try:
        d = Decimal(str(value).replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        raise ServiceError(f"{field} noto'g'ri.")
    if not d.is_finite():
        raise ServiceError(f"{field} noto'g'ri.")
    return d


def _ym(request, default: str | None = None) -> str:
    ym = request.query_params.get("month") or default or cur_month()
    if not _YM.match(ym):
        raise ServiceError("Oy YYYY-MM ko'rinishida bo'lishi kerak.")
    return ym


def _money_text_of(op: Operation) -> str:
    return f"{num(op.orig_amount)} $" if op.currency == "USD" else money(op.amount)


def _member_or_404(tg) -> TelegramMember:
    m = S.member_by_tg(tg)
    if not m:
        raise NotFound("Xodim topilmadi.")
    return m


# ===================================================================== config / catalogs
class ConfigView(BotAPIView):
    def get(self, request):
        self.require_member()
        return Response(self._data())

    @staticmethod
    def _data() -> dict:
        manual = S.D(config.FIN_USD_RATE)
        return {
            "channel_id": str(config.FIN_CHANNEL_ID or "").strip(),
            "usd_rate": D.dec(S.usd_rate(), 4),
            "usd_rate_manual": D.dec(manual, 4),
            "ready_days": int(config.FIN_READY_DAYS or 30),
            "version": f"{config.FIN_USD_RATE}|{config.FIN_CHANNEL_ID}|{config.FIN_READY_DAYS}",
        }


class UsdRateView(BotAPIView):
    def put(self, request):
        self.require_admin()
        S.set_usd_rate(request.data.get("rate"))
        return Response(ConfigView._data())


class MembersView(BotAPIView):
    """?set=staff|wallets|pending|active and/or ?duty=<field>."""

    def get(self, request):
        me = self.require_active() if request.query_params.get("set") == "wallets" else None
        kind = request.query_params.get("set")
        duty = request.query_params.get("duty")
        if not me:
            self.require_admin()
        if duty:
            if duty not in DUTIES:
                raise ServiceError("Noto'g'ri vazifa.")
            rows = list(TelegramMember.objects.filter(**{duty: True}).select_related("user"))
        elif kind == "staff":
            rows = S.staff()
        elif kind == "wallets":
            rows = S.wallets()
        elif kind == "pending":
            rows = list(
                TelegramMember.objects.filter(role=TelegramRole.PENDING).select_related("user")
            )
        elif kind == "active":
            rows = list(
                TelegramMember.objects.filter(
                    role__in=[TelegramRole.ADMIN, TelegramRole.STAFF]
                ).select_related("user")[:40]
            )
        else:
            raise ServiceError("set parametri kerak: staff, wallets, pending yoki active.")
        return Response([D.member_dto(m) for m in rows])


class MemberView(BotAPIView):
    def get(self, request, tg):
        me = self.require_member()
        if not (me.is_admin or me.telegram_id == tg):
            raise PermissionDenied("Bu ma'lumot faqat rahbar uchun.")
        return Response(D.member_dto(_member_or_404(tg)))


class MemberBalanceView(BotAPIView):
    def get(self, request, tg):
        me = self.require_active()
        if not (me.is_admin or me.telegram_id == tg):
            raise PermissionDenied("Bu ma'lumot faqat rahbar uchun.")
        return Response({"balance": D.dec(S.balance(_member_or_404(tg)))})


class MemberNameView(BotAPIView):
    def post(self, request, tg):
        self.require_admin()
        m = S.rename_member(_member_or_404(tg), request.data.get("name"))
        return Response(D.member_dto(m))


class MemberRoleView(BotAPIView):
    def post(self, request, tg):
        self.require_admin()
        role = request.data.get("role")
        if role not in (TelegramRole.STAFF, TelegramRole.BLOCKED):
            raise ServiceError("Rol staff yoki blocked bo'lishi kerak.")
        m = _member_or_404(tg)
        old = m.role
        S.set_member_role(m, role)
        if role == TelegramRole.STAFF and old != TelegramRole.STAFF:
            E.member_approved(m)
        return Response(D.member_dto(m))


class MemberDutyView(BotAPIView):
    def post(self, request, tg):
        self.require_admin()
        m = _member_or_404(tg)
        duty = request.data.get("duty")
        if not m.is_active_member:
            raise ServiceError("Vazifa faqat tasdiqlangan xodimga beriladi.")
        S.set_duty_exclusive(m, duty)
        m.refresh_from_db()
        E.duty_assigned(m, duty)
        return Response(D.member_dto(m))


class CategoriesView(BotAPIView):
    def get(self, request):
        self.require_active()
        return Response(
            [D.category_dto(c) for c in S.categories(request.query_params.get("kind") or None)]
        )


class WorkersView(BotAPIView):
    def get(self, request):
        self.require_active()
        return Response([D.worker_dto(w) for w in Worker.objects.filter(is_active=True)])


class CarsView(BotAPIView):
    def get(self, request):
        self.require_active()
        return Response([D.car_dto(c) for c in FinanceCar.objects.filter(is_active=True)])


class ParseView(BotAPIView):
    """Free text -> a quick entry (`mode=quick`) or an amount (`mode=money`)."""

    def post(self, request):
        self.require_active()
        text = str(request.data.get("text") or "")
        mode = request.data.get("mode") or "quick"
        if mode == "money":
            val, _cur = parse_money(text)
            if not val:
                return Response(None)
            m = S.money_in(text)  # 400 when it is dollars and there is no rate
            return Response(
                {
                    "amount": D.dec(m["amount"]),
                    "cur": m["cur"],
                    "orig": D.dec(m["orig"]),
                    "rate": D.dec(m["rate"], 4),
                }
            )
        if mode != "quick":
            raise ServiceError("mode: quick yoki money.")
        q = parse_quick(text, S.all_order_ids(), S.categories())
        if not q:
            return Response(None)
        return Response({**q, "val": str(q["val"])})


# ===================================================================== orders
def _briefs(infos):
    return Response([D.order_brief_dto(i) for i in infos])


class OrdersView(BotAPIView):
    def get(self, request):
        self.require_active()
        buckets = [b for b in (request.query_params.get("buckets") or "jarayonda").split(",") if b]
        if not buckets or set(buckets) - BUCKETS:
            raise ServiceError("Noto'g'ri buckets.")
        return _briefs(S.open_orders(buckets))


class OrdersArchiveView(BotAPIView):
    def get(self, request):
        self.require_active()
        return _briefs(S.archive_orders())


class OrdersClosedManualView(BotAPIView):
    def get(self, request):
        self.require_admin()
        rows = ManualOrder.objects.filter(is_closed=True)[:30]
        return Response(
            [
                {
                    "ref": o.ref,
                    "client": o.client,
                    "bucket": "tugadi",
                    "ready_date": D.iso(o.closed),
                }
                for o in rows
            ]
        )


class OrdersNextRefView(BotAPIView):
    def get(self, request):
        self.require_admin()
        return Response({"ref": S.next_manual_ref()})


class OrderCardView(BotAPIView):
    def get(self, request, ref):
        me = self.require_active()
        info = S.order_info(ref)
        if not info:
            raise NotFound("Buyurtma topilmadi.")
        # contract money (total / paid / rest / price_uzs) only for finance admins
        return Response(D.order_card_dto(info, S.order_stats(info.ref), full=me.is_admin))


# ===================================================================== reports
def _scope(view: BotAPIView, request):
    """(member or None for the whole company, label). Non-admins always get themselves."""
    me = view.require_active()
    raw = request.query_params.get("member") or str(me.telegram_id)
    if not me.is_admin:
        return me, str(me.telegram_id)
    if raw == "all":
        return None, "all"
    return _member_or_404(raw), str(raw)


def _summary_dto(sm: dict) -> dict:
    def cats(items):
        return [
            {
                "code": i["code"],
                "name": i["name"],
                "emoji": i["emoji"],
                "sum": D.dec(i["sum"]),
                "n": i["n"],
            }
            for i in items
        ]

    return {
        **D.day_summary_dto(sm),
        "expense_by_category": cats(sm["expense_by_category"]),
        "income_by_category": cats(sm["income_by_category"]),
        "salary_by_worker": [{"name": n, "sum": D.dec(v)} for n, v in sm["salary_by_worker"]],
    }


class SummaryView(BotAPIView):
    def get(self, request):
        member, scope = _scope(self, request)
        ym = _ym(request)
        s, e = month_bounds(ym)
        sm = S.summary(s, e, member)
        return Response(
            {
                "month": ym,
                "scope": scope,
                "member": D.member_dto(member),
                "summary": _summary_dto(sm),
                "member_balance": D.dec(S.balance(member)) if member else None,
            }
        )


class OperationsView(BotAPIView):
    def get(self, request):
        member, scope = _scope(self, request)
        ym = _ym(request)
        s, e = month_bounds(ym)
        rows = S.period_ops(s, e, member).select_related("author").order_by("-date", "-number")
        return Response(
            {
                "month": ym,
                "scope": scope,
                "rows": [D.operation_row_dto(t, scope_all=member is None) for t in rows],
            }
        )

    def post(self, request):
        me = self.require_active()
        d = request.data
        target = S.member_by_tg(d.get("member_tg") or me.telegram_id)
        if not target:
            raise NotFound("Xodim topilmadi.")
        cur = d.get("currency") or "UZS"
        op = S.create_operation_as(
            me,
            target,
            kind=d.get("kind"),
            amount=_dec(d.get("amount")),
            category_code=d.get("category"),
            currency=cur,
            orig_amount=_dec(d["orig_amount"]) if d.get("orig_amount") else None,
            rate=_dec(d["rate"]) if d.get("rate") else None,
            order_ref=d.get("order_ref") or None,
            comment=d.get("comment") or "",
            receipt_file_id=d.get("receipt_file_id") or "",
            worker=d.get("worker") or "",
            pay_type=d.get("pay_type") or "",
        )
        E.operation_created(op, author=me)
        return Response(
            {"operation": D.operation_dto(op), "balance": D.dec(S.balance(op.member))}, status=201
        )


def _op_or_404(number: int) -> Operation:
    op = (
        Operation.objects.select_related("member", "category", "author")
        .filter(number=number)
        .first()
    )
    if not op:
        raise NotFound("Amal topilmadi.")
    return op


class OperationView(BotAPIView):
    def get(self, request, number):
        me = self.require_active()
        op = _op_or_404(number)
        can_delete = S.can_delete(me, op)
        if not (me.is_admin or can_delete or op.member_id == me.pk or op.author_id == me.pk):
            raise PermissionDenied("Bu amal sizniki emas.")
        can_attach = bool(not op.is_deleted and (me.is_admin or op.author_id == me.pk))
        return Response({**D.operation_dto(op), "can_delete": can_delete, "can_attach": can_attach})

    def delete(self, request, number):
        me = self.require_active()
        deleted = S.delete_operation_as(me, number)
        E.operation_deleted(deleted, me.name)
        return Response({"deleted": [D.operation_dto(t) for t in deleted]})


class OperationReceiptView(BotAPIView):
    def post(self, request, number):
        me = self.require_active()
        op = S.attach_receipt(_op_or_404(number), str(request.data.get("file_id") or ""), me)
        E.receipt_attached(op, op.receipt_file_id)
        return Response(D.operation_dto(op))


class MonthsView(BotAPIView):
    def get(self, request):
        member, scope = _scope(self, request)
        return Response(
            {
                "scope": scope,
                "member": D.member_dto(member),
                "series": [
                    {
                        "month": x["month"],
                        "label": x["label"],
                        "income": D.dec(x["income"]),
                        "expense": D.dec(x["expense"]),
                    }
                    for x in S.months_series(member)
                ],
            }
        )


class WalletsView(BotAPIView):
    def get(self, request):
        self.require_admin()
        w = S.wallets_overview()
        return Response(
            {
                "report_month": w["report_month"],
                "rows": [
                    {
                        "member": D.member_dto(r["member"]),
                        "balance": D.dec(r["balance"]),
                        "last_day": D.iso(r["last_day"]),
                        "reported": r["reported"],
                        "month_spent": D.dec(r["month_spent"]),
                    }
                    for r in w["rows"]
                ],
                "pending": [D.member_dto(m) for m in w["pending"]],
                "staff_total": D.dec(w["staff_total"]),
            }
        )


class ChecksView(BotAPIView):
    def get(self, request):
        self.require_admin()
        return Response(S.checks())


class ExcelView(BotAPIView):
    def get(self, request):
        self.require_admin()
        return _xlsx_response(*month_xlsx(_ym(request)))


def _xlsx_response(content: bytes, name: str) -> HttpResponse:
    resp = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="{name}"'
    return resp


class MonthReportExcelView(BotAPIView):
    """One person's month as xlsx (sent to the admins with «📤 Oylik hisob»).
    Admins may ask for anyone; staff only get their own."""

    def get(self, request):
        me = self.require_active()
        raw = request.query_params.get("member")
        if not raw or str(raw) == str(me.telegram_id):
            member = me
        elif me.is_admin:
            member = _member_or_404(raw)
        else:
            raise PermissionDenied("Bu amal faqat rahbar uchun.")
        ym = _ym(request, S.month_report_target(member))
        return _xlsx_response(*member_month_xlsx(member, ym))


class MonthReportView(BotAPIView):
    def get(self, request):
        me = self.require_active()
        ym = S.month_report_target(me)
        from accounting.models import MonthReport

        sm = S.month_summary(me, ym)
        return Response(
            {
                **D.month_summary_dto(sm),
                "submitted": MonthReport.objects.filter(member=me, month=ym).exists(),
            }
        )

    def post(self, request):
        me = self.require_active()
        if me.is_task_only:
            raise PermissionDenied("Siz oylik hisob topshirmaysiz.")
        ym = str(request.data.get("month") or S.month_report_target(me))
        if not _YM.match(ym) or ym > cur_month():
            raise ServiceError("Oy noto'g'ri.")
        rep = S.submit_month(me, ym, str(request.data.get("note") or ""))
        sm = S.month_summary(me, ym)
        E.month_submitted(me, rep, sm)
        return Response(
            {
                "report": {
                    "month": rep.month,
                    "balance": D.dec(rep.balance),
                    "note": rep.note,
                    "submitted_at": rep.submitted_at.strftime("%Y-%m-%dT%H:%M:%S"),
                },
                "summary": D.month_summary_dto(sm),
            }
        )


# ===================================================================== handover, warranty, tasks
class HandoverListView(BotAPIView):
    def get(self, request):
        self.require_admin()
        return Response([D.operation_dto(t) for t in S.handover_pending()])


class _HandoverAction(BotAPIView):
    action = ""

    def post(self, request, number):
        boss = self.require_admin()
        op = (
            Operation.objects.select_related("member", "category", "author")
            .filter(number=number)
            .first()
        )
        if not op or (op.is_deleted and op.handover != "deleted"):
            raise NotFound(f"#{number} yozuvi topilmadi yoki o'chirilgan.")
        info = S.order_info(op.order_ref)
        client = info.client if info else ""
        sum_text = _money_text_of(op)
        if self.action == "drop":
            S.handover_drop(op)
        else:
            S.handover_accept(op, boss)
        op.refresh_from_db()
        E.handover_resolved(op, self.action, client, sum_text)
        return Response(
            {
                "operation": D.operation_dto(
                    Operation.objects.select_related("member", "category", "author").get(pk=op.pk)
                ),
                "client": client,
                "sum_text": sum_text,
                "member_balance": D.dec(S.balance(op.member)),
            }
        )


class HandoverAcceptView(_HandoverAction):
    action = "accept"


class HandoverDropView(_HandoverAction):
    action = "drop"


class WarrantyListView(BotAPIView):
    def get(self, request):
        self.require_receiver()
        qs = WarrantyLetter.objects.all()
        if request.query_params.get("given") in ("0", "1"):
            qs = qs.filter(given=request.query_params["given"] == "1")
        return Response([D.warranty_dto(w) for w in qs.order_by("-id")[:50]])


class WarrantyGiveView(BotAPIView):
    def post(self, request, ref):
        me = self.require_receiver()
        w = S.warranty_give(ref, me.name)
        if not me.is_admin:
            E.warranty_given(w, me.name)
        return Response(D.warranty_dto(w))


class TasksView(BotAPIView):
    def get(self, request):
        m = self.require_active()
        site, fb = [], []
        if m.is_admin or m.is_site_entry:
            site = [D.task_dto(t) for t in SiteEntryTask.objects.filter(is_done=False)[:15]]
        if m.is_admin or m.is_feedback:
            fb = [D.feedback_dto(f) for f in ClientFeedback.objects.filter(status="asked")[:15]]
        return Response({"site_entry": site, "feedback": fb})


class SiteEntryDoneView(BotAPIView):
    def post(self, request, code):
        me = self.require_duty("is_site_entry")
        task = SiteEntryTask.objects.filter(code=code).first()
        if not task:
            raise NotFound("Vazifa topilmadi.")
        task = S.site_entry_done(task, me.name)
        E.site_entry_done(task, me.name)
        return Response(D.task_dto(task))


# ===================================================================== requests, transfers, join
def _req_or_404(number: int) -> MoneyRequest:
    req = (
        MoneyRequest.objects.select_related("member", "member__user").filter(number=number).first()
    )
    if not req:
        raise NotFound("So'rov topilmadi.")
    return req


class RequestsView(BotAPIView):
    def post(self, request):
        me = self.require_active()
        req = S.request_money(
            me, str(request.data.get("amount_text") or ""), str(request.data.get("reason") or "")
        )
        E.request_created(req)
        return Response(D.request_dto(req), status=201)


class RequestView(BotAPIView):
    def get(self, request, number):
        self.require_admin()
        return Response(D.request_dto(_req_or_404(number)))


class RequestGiveView(BotAPIView):
    def post(self, request, number):
        boss = self.require_admin()
        req = _req_or_404(number)
        m = S.request_amount(req, request.data.get("amount_text"))
        op = S.give_request(req, boss, m)
        req = _req_or_404(number)
        E.request_answered(req, "given", boss.name, False, op)
        return Response(
            {
                "request": D.request_dto(req),
                "operation": D.operation_dto(op),
                "balance": D.dec(S.balance(req.member)),
            }
        )


class RequestRejectView(BotAPIView):
    def post(self, request, number):
        boss = self.require_admin()
        req = S.reject_request(_req_or_404(number), boss)
        req = _req_or_404(number)
        E.request_answered(req, "rejected", boss.name, False)
        return Response(D.request_dto(req))


class RequestMessagesView(BotAPIView):
    def post(self, request, number):
        me = self.require_active()
        req = _req_or_404(number)
        if not (me.is_admin or req.member_id == me.pk):
            raise PermissionDenied("Bu so'rov sizniki emas.")
        if req.status != "pending":
            raise ServiceError("Bu so'rovga allaqachon javob berilgan.")
        S.set_request_messages(req, request.data.get("messages") or [])
        return Response(status=204)


class TransfersView(BotAPIView):
    def post(self, request):
        me = self.require_active()
        to = _member_or_404(request.data.get("to_tg"))
        out, inc = S.create_transfer(
            sender=me,
            receiver=to,
            amount=_dec(request.data.get("amount")),
            comment=str(request.data.get("comment") or "")[:300],
            author=me,
        )
        out = Operation.objects.select_related("member", "category", "author").get(pk=out.pk)
        inc = Operation.objects.select_related("member", "category", "author").get(pk=inc.pk)
        E.transfer_created(out, inc, me)
        return Response(
            {
                "out": D.operation_dto(out),
                "inc": D.operation_dto(inc),
                "balance": D.dec(S.balance(me)),
            },
            status=201,
        )


class JoinView(BotAPIView):
    """Anyone may ask to join; an admin approves. Never linked to a site account."""

    def post(self, request):
        tg = self.require_actor()
        m, created = S.register_member(
            tg, str(request.data.get("name") or ""), str(request.data.get("username") or "")
        )
        if created:
            E.join_requested(m)
        return Response(
            {"member": D.member_dto(m), "created": created}, status=201 if created else 200
        )


# ===================================================================== manual orders
class ManualOrdersView(BotAPIView):
    def post(self, request):
        self.require_admin()
        price_text = str(request.data.get("price_text") or "").strip()
        price = S.money_in(price_text)["amount"] if price_text else 0
        mo = S.create_manual_order(
            str(request.data.get("ref") or ""),
            str(request.data.get("client") or ""),
            str(request.data.get("phone") or ""),
            price,
        )
        E.manual_order_created(mo)
        return Response(D.order_brief_dto(S.order_info(mo.ref)), status=201)


class ManualOrderView(BotAPIView):
    def patch(self, request, ref):
        self.require_admin()
        d = request.data
        if d.get("price_text") not in (None, ""):
            mo = S.set_manual_price(ref, str(d["price_text"]))
        elif d.get("toggle_closed"):
            mo = S.toggle_manual_order(ref)
            if mo.is_closed:
                E.manual_order_closed(mo)
        else:
            raise ServiceError("price_text yoki toggle_closed kerak.")
        info = S.order_info(mo.ref)
        return Response(D.order_card_dto(info, S.order_stats(info.ref), full=True))


# ===================================================================== bonus
def _bonus_or_temp(ref: str, or_temp: bool) -> OrderBonus:
    bn = OrderBonus.objects.filter(order_ref=ref).first()
    if bn:
        return bn
    info = S.order_info(ref)
    if not (or_temp and info):
        raise NotFound("Bonus topilmadi.")
    return OrderBonus(
        order_ref=info.ref,
        client=info.client,
        description=info.furniture,
        total=info.total,
        currency=info.currency,
        ready_date=info.ready_date or today(),
        phone=info.phone,
    )


class BonusView(BotAPIView):
    def get(self, request, ref):
        me = self.require_receiver()
        bn = _bonus_or_temp(ref, request.query_params.get("or_temp") == "1")
        ms = S.money_state(bn)
        return Response(
            {
                "bonus": D.bonus_dto(bn),
                "money_state": D.money_state_dto(ms),
                "tolerance": D.dec(S.bonus_tolerance(bn.currency)),
                "is_receiver": followup.is_receiver(me),
                "usd_rate": D.dec(S.usd_rate(), 4),
                "percent_now": D.dec(S.bonus_percent(max(0, days_between(bn.ready_date, today())))),
            }
        )


class BonusCardView(BotAPIView):
    def get(self, request, ref):
        self.require_receiver()
        bn = _bonus_or_temp(ref, request.query_params.get("or_temp") == "1")
        png = report_card_png(card_values(bn, S.money_state(bn)["paid"]))
        return HttpResponse(png, content_type="image/png")


class BonusCollectView(BotAPIView):
    def post(self, request, ref):
        me = self.require_receiver()
        res = S.bonus_collect_flow(
            ref, me, str(request.data.get("amount_text") or ""), bool(request.data.get("full"))
        )
        bn, op, task = res["bonus"], res["operation"], res["task"]
        if not task.is_done:  # a manual order: the site entry manager still enters it
            E.site_entry_created(task, me.name)
        if not me.is_admin:
            E.handover_requested(
                op, me.name, bn.order_ref, bn.client, res["sum_text"], res["rest_text"]
            )
        if res["full"]:
            E.bonus_done(bn)
        return Response(
            {
                "bonus": D.bonus_dto(bn),
                "rest": D.dec(res["rest"]),
                "rest_text": res["rest_text"],
                "sum_text": res["sum_text"],
                "full": res["full"],
                "operation": D.operation_dto(op),
                "task": D.task_dto(task),
            }
        )


class BonusCloseView(BotAPIView):
    def post(self, request, ref):
        me = self.require_receiver()
        bn = S.bonus_close(ref, me.name)
        E.bonus_done(bn)
        return Response(D.bonus_dto(bn))


# ===================================================================== feedback, template
class FeedbackView(BotAPIView):
    def get(self, request, ref):
        self.require_duty("is_feedback")
        fb = ClientFeedback.objects.filter(order_ref=str(ref)).first()
        if not fb:
            raise NotFound("Fikr topilmadi.")
        return Response(D.feedback_dto(fb))

    def post(self, request, ref):
        me = self.require_duty("is_feedback")
        upload = request.FILES.get("file")
        fb = S.receive_feedback_photo(
            ref,
            me.name,
            str(request.data.get("caption") or ""),
            str(request.data.get("file_id") or ""),
            upload.read() if upload else None,
        )
        E.feedback_received(fb, me.name, fb.text, fb.screenshot_file_id)
        return Response(D.feedback_dto(fb))


class ReportTemplateView(BotAPIView):
    def post(self, request):
        self.require_admin()
        upload = request.FILES.get("file")
        if not upload:
            raise ServiceError("Rasm yuborilmadi.")
        S.set_report_template(upload.read())
        return Response(status=204)

    def delete(self, request):
        self.require_admin()
        S.reset_report_template()
        return Response(status=204)
