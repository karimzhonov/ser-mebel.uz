"""Selectors for the Call-center kanban on the admin dashboard."""

from django.db.models import Q
from django.urls import reverse

from core.kanban import DANGER, INFO, OK, PRIMARY, WARN, Column, build_board

from .constants import SolutionChoice


def call_center_board() -> list[dict]:
    """Columns for the "Call-center" kanban.

    One column per SolutionChoice, plus Янги for invoices nobody has answered yet
    (`solution` defaults to NULL). The four dead-end answers start collapsed.
    """
    from .models import Invoice

    changelist = reverse("admin:call_center_invoice_changelist")

    def by_solution(solution):
        return f"{changelist}?solution={solution.value}"

    columns = [
        Column("new", "Янги", "fiber_new", PRIMARY,
               Q(solution__isnull=True), more_url=f"{changelist}?solution__isnull=True"),
        Column("re_phone", SolutionChoice.re_phone.label, "warning", WARN,
               Q(solution=SolutionChoice.re_phone),
               more_url=by_solution(SolutionChoice.re_phone)),
        Column("given_info", SolutionChoice.given_info.label, "info", INFO,
               Q(solution=SolutionChoice.given_info),
               more_url=by_solution(SolutionChoice.given_info)),
        Column("given_location", SolutionChoice.given_location.label, "pin_drop", INFO,
               Q(solution=SolutionChoice.given_location),
               more_url=by_solution(SolutionChoice.given_location)),
        Column("go_for_measured", SolutionChoice.go_for_measured.label, "check", OK,
               Q(solution=SolutionChoice.go_for_measured),
               more_url=by_solution(SolutionChoice.go_for_measured)),
        Column("sold_out", SolutionChoice.sold_out.label, "done_all", OK,
               Q(solution=SolutionChoice.sold_out), collapsed=True,
               more_url=by_solution(SolutionChoice.sold_out)),
        Column("price_problem", SolutionChoice.price_problem.label, "close", DANGER,
               Q(solution=SolutionChoice.price_problem), collapsed=True,
               more_url=by_solution(SolutionChoice.price_problem)),
        Column("dont_need", SolutionChoice.dont_need.label, "close", DANGER,
               Q(solution=SolutionChoice.dont_need), collapsed=True,
               more_url=by_solution(SolutionChoice.dont_need)),
        Column("declined", SolutionChoice.declined.label, "close", DANGER,
               Q(solution=SolutionChoice.declined), collapsed=True,
               more_url=by_solution(SolutionChoice.declined)),
    ]

    queryset = Invoice.objects.select_related("client").order_by("-create_date")

    return build_board(queryset, columns, _invoice_card)


def _invoice_card(invoice) -> dict:
    return {
        "url": reverse("admin:call_center_invoice_change", args=[invoice.pk]),
        "number": invoice.pk,
        "client": str(invoice.client),
        "phone": str(invoice.client.phone),
        "desc": (invoice.desc or "").strip(),
        "when": invoice.create_date,
    }
