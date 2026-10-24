"""GET /api/v1/dashboard/overview/?date_from=&date_to=&currency=

One screen for the whole furniture-to-order process: sales funnel, order pipeline,
deadlines, money, production load and the metering schedule. Every block is only
built for a user who may see that model (same permissions as the list pages); a
block the user may not see is returned as null.

"In the period" numbers use the date range; "now" numbers (orders per stage,
overdue, debt, production queues) are snapshots that ignore it.
"""

from collections import defaultdict
from datetime import datetime, timedelta

from django.db.models import Count, ExpressionWrapper, F, FloatField, Min, Q, Sum
from djmoney import settings as dj_settings
from rest_framework.response import Response
from rest_framework.views import APIView

from accounting.models import Expense, Income
from call_center.constants import SolutionChoice
from call_center.models import Invoice
from metering.constants import MeteringStatus
from metering.models import Metering
from order.assembly.constants import ASSEMBLY_MANAGER_PERMISSION
from order.assembly.models import Assembly
from order.constants import ORDER_VIEW_PRICE_PERMISSION, OrderStatus
from order.detailing.models import Detailing
from order.models import Order
from order.painter.models import Painter
from order.painter.services import ready_for_painter
from order.rover.models import Rover

from ..serializers.common import UserShortSerializer, money_left
from ..utils import (
    apply_period,
    date_range,
    monthly_buckets,
    order_deadline,
    timeseries,
    today,
    warning_filter,
    warning_order_days,
)

MEASURED = [MeteringStatus.metering_done, MeteringStatus.done, MeteringStatus.sold_out]
OPEN_METERING = [MeteringStatus.created, MeteringStatus.other_day]
LIVE_ORDER = [OrderStatus.WAITING, *OrderStatus.active_statuses()]


def _pct(part, whole):
    return round(part * 100 / whole) if whole else None


class OverviewView(APIView):
    def get(self, request):
        params = request.query_params
        start, end = date_range(params)
        user = request.user
        return Response(
            {
                "range": {"from": start, "to": end},
                "monthly": monthly_buckets(params),
                "funnel": self.funnel(user, params),
                "orders": self.orders(user, params),
                "money": self.money(user, params),
                "accounting": self.accounting(user, params),
                "production": self.production(user),
                "meterings": self.meterings(user),
                "call_center": self.call_center(user),
                "timeline": self.timeline(user, params),
            }
        )

    # --- sales funnel -------------------------------------------------------------

    def funnel(self, user, params):
        steps = []
        if user.has_perm("call_center.view_invoice"):
            invoices = apply_period(Invoice.objects.all(), "create_date", params)
            steps.append({"key": "invoices", "label": "Заявки", "count": invoices.count()})
        if user.has_perm("metering.view_metering"):
            # One cohort: the meterings created in the period, followed to the order.
            m = apply_period(Metering.objects.all(), "create_date", params)
            agg = m.aggregate(
                total=Count("pk"),
                measured=Count("pk", filter=Q(status__in=MEASURED)),
                design=Count("pk", filter=Q(design__done=True)),
                price=Count("pk", filter=Q(price__done=True)),
                sold=Count("pk", filter=Q(order__isnull=False)),
                cancelled=Count("pk", filter=Q(status=MeteringStatus.dont_need)),
            )
            steps += [
                # Different cohort from the invoices above (meterings by their own
                # create_date), so no conversion is computed into this step.
                {
                    "key": "meterings",
                    "label": "Замеры назначены",
                    "count": agg["total"],
                    "cohort": True,
                },
                {"key": "measured", "label": "Замер выполнен", "count": agg["measured"]},
            ]
            # Same permissions as the Дизайн / Нарх list pages.
            if user.has_perm("design.view_design"):
                steps.append({"key": "design", "label": "Дизайн готов", "count": agg["design"]})
            if user.has_perm("price.view_price"):
                steps.append({"key": "price", "label": "Цена рассчитана", "count": agg["price"]})
            steps.append({"key": "sold", "label": "Заказ оформлен", "count": agg["sold"]})
            cancelled = agg["cancelled"]
        else:
            cancelled = None
        if not steps:
            return None
        for prev, step in zip([None, *steps], steps):
            new_cohort = step.pop("cohort", False)
            step["conversion"] = (
                _pct(step["count"], prev["count"]) if prev and not new_cohort else None
            )
        # Overall conversion within the metering cohort (meterings -> orders).
        cohort = next((s for s in steps if s["key"] == "meterings"), None)
        return {
            "steps": steps,
            "total_conversion": _pct(steps[-1]["count"], cohort["count"]) if cohort else None,
            "cancelled": cancelled,
        }

    # --- orders ---------------------------------------------------------------------

    def orders(self, user, params):
        if not user.has_perm("order.view_order"):
            return None
        t = today()
        live = Order.objects.filter(status__in=LIVE_ORDER)
        by_status = dict(
            live.order_by().values_list("status").annotate(c=Count("pk")).values_list("status", "c")
        )
        overdue = warning_filter(live, "danger")  # same rows as /orders?warning=danger
        due_soon = live.filter(
            end_date__gte=t, end_date__lte=t + timedelta(days=warning_order_days())
        )

        # "Done in the period": first history row with status=done falls in the range.
        start, end = date_range(params)
        done_first = (
            # Deletion rows also carry the last status; they are not "finished".
            # Orders finished before history existed are not counted.
            Order.history.filter(status=OrderStatus.DONE)
            .exclude(history_type="-")
            .values("id")
            .annotate(first=Min("history_date"))
        )
        if start:
            done_first = done_first.filter(first__date__gte=start)
        if end:
            done_first = done_first.filter(first__date__lte=end)

        upcoming = (
            live.exclude(status=OrderStatus.WAITING)
            .filter(end_date__isnull=False)
            .select_related("client")
            .order_by("end_date")[:8]
        )
        factories = (
            live.order_by()
            .values("factory_id", "factory__name")
            .annotate(count=Count("pk"))
            .order_by("-count")
        )
        return {
            "by_status": [
                {"key": s, "count": by_status.get(s, 0)} for s in [s.value for s in LIVE_ORDER]
            ],
            "active": sum(by_status.values()),
            "overdue": overdue.count(),
            "due_soon": due_soon.count(),
            "new": apply_period(Order.objects.all(), "reception_date", params).count(),
            "done": done_first.count(),
            "deadlines": [
                {
                    "id": o.pk,
                    "number": o.order_number,
                    "client": str(o.client) if o.client_id else "—",
                    "status": o.status,
                    "end_date": o.end_date,
                    "deadline": order_deadline(o),
                }
                for o in upcoming
            ],
            "factories": [
                {"name": row["factory__name"], "count": row["count"]} for row in factories
            ],
        }

    # --- money on orders ------------------------------------------------------------

    def money(self, user, params):
        # Same gate as the order money columns: must see orders AND their prices.
        if not user.has_perms(["order.view_order", f"order.{ORDER_VIEW_PRICE_PERMISSION}"]):
            return None
        received = apply_period(Order.objects.all(), "reception_date", params).order_by()
        contracts = (
            received.filter(price__isnull=False)
            .values("price_currency")
            .annotate(
                total=Sum(
                    ExpressionWrapper(
                        F("price") * (1 - F("discount") / 100.0), output_field=FloatField()
                    )
                )
            )
        )
        paid = (
            received.filter(lost_money__isnull=False)
            .values("lost_money_currency")
            .annotate(total=Sum("lost_money"))
        )
        # Debt needs the per-order currency check (money_left), so it stays in Python,
        # but only over live orders and only the columns it reads.
        live = Order.objects.filter(status__in=LIVE_ORDER).only(
            "price", "price_currency", "lost_money", "lost_money_currency", "discount", "status"
        )
        debt = []
        for order in live:
            left = money_left(order)
            if left and left["amount"] > 0:
                debt.append(left)
        debt_total = defaultdict(float)
        for d in debt:
            debt_total[d["currency"]] += d["amount"]
        return {
            "contracts": [
                {"amount": round(float(r["total"] or 0), 2), "currency": r["price_currency"]}
                for r in contracts
            ],
            "paid": [
                {"amount": round(float(r["total"] or 0), 2), "currency": r["lost_money_currency"]}
                for r in paid
            ],
            "debt": [{"amount": round(v, 2), "currency": c} for c, v in sorted(debt_total.items())],
            "debtors": len(debt),
        }

    # --- income / expense -------------------------------------------------------------

    def accounting(self, user, params):
        can_in = user.has_perm("accounting.view_income")
        can_out = user.has_perm("accounting.view_expense")
        if not (can_in or can_out):
            return None
        currency = params.get("currency") or dj_settings.DEFAULT_CURRENCY

        def total(model):
            qs = model.objects.all()
            if not user.is_superuser:  # same scoping as the Приходы/Расходы lists
                qs = qs.filter(user=user)
            qs = apply_period(qs, "created_at", params)
            return round(float(qs.aggregate(s=Sum("converted_cost"))["s"] or 0), 2)

        income = total(Income) if can_in else None
        expense = total(Expense) if can_out else None
        return {
            "currency": currency,
            "income": income,
            "expense": expense,
            "profit": round(income - expense, 2) if can_in and can_out else None,
        }

    # --- production queues ------------------------------------------------------------

    def production(self, user):
        manager = user.has_perm(f"assembly.{ASSEMBLY_MANAGER_PERMISSION}")
        stages = []

        def stage(key, label, qs, link):
            agg = qs.aggregate(count=Count("pk"), square=Sum("square"))
            stages.append(
                {
                    "key": key,
                    "label": label,
                    "count": agg["count"],
                    "square": round(agg["square"] or 0, 1),
                    "link": link,
                }
            )

        if user.has_perm("detailing.view_detailing"):
            stage(
                "detailing",
                "Деталировка",
                Detailing.objects.filter(done=False),
                "/production/detailing",
            )
        if user.has_perm("rover.view_rover"):
            stage("rover", "Ровер", Rover.objects.filter(done=False), "/production/rover")
        if user.has_perm("painter.view_painter"):
            painters = ready_for_painter(Painter.objects.filter(done=False))
            if not manager:
                painters = painters.filter(type__user=user)
            stage("painter", "Моляр", painters, "/production/painter")
        workload = None
        if user.has_perm("assembly.view_assembly"):
            assemblies = Assembly.objects.all()
            if not manager:
                assemblies = assemblies.filter(user=user)
            stage(
                "assembly",
                "Сборка",
                assemblies.filter(done=False),
                "/production/assembly",
            )
            stage(
                "installing",
                "Установка",
                assemblies.filter(done=True, installing_done=False),
                "/production/assembly",
            )
            if manager:
                rows = (
                    Assembly.objects.filter(installing_done=False)
                    .order_by()
                    .values("user")
                    .annotate(count=Count("pk"), square=Sum("square"))
                    .order_by("-count")
                )
                users = {
                    u.pk: u
                    for u in type(user).objects.filter(
                        pk__in=[r["user"] for r in rows if r["user"]]
                    )
                }
                workload = [
                    {
                        "user": UserShortSerializer(users[r["user"]]).data if r["user"] else None,
                        "count": r["count"],
                        "square": round(r["square"] or 0, 1),
                    }
                    for r in rows
                ]
        if not stages:
            return None
        return {"stages": stages, "assemblers": workload}

    # --- metering schedule ------------------------------------------------------------

    def meterings(self, user):
        if not user.has_perm("metering.view_metering"):
            return None
        now = datetime.now()
        open_ = Metering.objects.filter(status__in=OPEN_METERING)
        upcoming = (
            open_.filter(date_time__gte=now).select_related("client").order_by("date_time")[:8]
        )
        return {
            "missed": open_.filter(date_time__lt=now).count(),
            "today": open_.filter(date_time__date=now.date()).count(),
            "upcoming": [
                {
                    "id": m.pk,
                    "client": str(m.client),
                    "phone": str(m.client.phone),
                    "address": m.address or "",
                    "when": m.date_time,
                }
                for m in upcoming
            ],
        }

    def call_center(self, user):
        if not user.has_perm("call_center.view_invoice"):
            return None
        return {
            "unanswered": Invoice.objects.filter(solution__isnull=True).count(),
            "callback": Invoice.objects.filter(solution=SolutionChoice.re_phone).count(),
        }

    # --- combined chart ---------------------------------------------------------------

    def timeline(self, user, params):
        series = {}
        if user.has_perm("call_center.view_invoice"):
            qs = apply_period(Invoice.objects.all(), "create_date", params)
            series["invoices"] = timeseries(qs, "create_date", params)
        if user.has_perm("metering.view_metering"):
            qs = apply_period(Metering.objects.all(), "create_date", params)
            series["meterings"] = timeseries(qs, "create_date", params)
        if user.has_perm("order.view_order"):
            qs = apply_period(Order.objects.all(), "reception_date", params)
            series["orders"] = timeseries(qs, "reception_date", params)
        merged = defaultdict(dict)
        for name, points in series.items():
            for p in points:
                # Monthly buckets on a DateTimeField come back as datetimes — key by day.
                merged[(p["date"] or "")[:10]][name] = p["value"]
        return {
            "series": list(series),
            "points": [
                {"date": day, **{name: values.get(name, 0) for name in series}}
                for day, values in sorted(merged.items())
                if day
            ],
        }
