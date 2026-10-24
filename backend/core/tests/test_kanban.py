"""The /admin/ dashboard kanban boards: column derivation and permission gating."""

import datetime

import pytest
from django.urls import reverse

from call_center.constants import SolutionChoice
from call_center.models import Invoice
from call_center.services import call_center_board
from metering.constants import MeteringStatus
from metering.models import Metering
from metering.services import metering_board
from order.constants import OrderStatus
from order.services import order_board


def column(board, key):
    return next(col for col in board if col["key"] == key)


def keys_holding(board, predicate):
    """Every column key whose cards satisfy `predicate` — used to prove a record
    shows up in exactly one column."""
    return [col["key"] for col in board for card in col["cards"] if predicate(card)]


# --- Заказы -----------------------------------------------------------------


@pytest.mark.django_db
def test_order_lands_in_exactly_one_column(order_factory, today, superuser):
    order = order_factory(end_date=today + datetime.timedelta(days=30))
    order.status = OrderStatus.DETAILING
    order.save(update_fields=["status"])

    board = order_board(user=superuser, show_price=True)

    assert keys_holding(board, lambda c: c["number"] == order.order_number) == ["detailing"]


@pytest.mark.django_db
def test_working_order_with_unfinished_rover_sits_in_the_rover_column(
    order_factory, today, superuser
):
    from order.rover.models import Rover

    order = order_factory(end_date=today + datetime.timedelta(days=30))
    order.status = OrderStatus.WORKING
    order.save(update_fields=["status"])
    Rover.objects.create(order=order, square=5)

    board = order_board(user=superuser, show_price=True)

    assert keys_holding(board, lambda c: c["number"] == order.order_number) == ["rover"]
    assert column(board, "working")["count"] == 0


@pytest.mark.django_db
def test_rover_done_moves_the_order_on_to_the_painter_column(order_factory, today, superuser):
    from order.painter.models import Painter
    from order.rover.models import Rover

    order = order_factory(end_date=today + datetime.timedelta(days=30))
    order.status = OrderStatus.WORKING
    order.save(update_fields=["status"])
    Rover.objects.create(order=order, square=5, done=True)
    Painter.objects.create(order=order, square=5)

    board = order_board(user=superuser, show_price=True)

    assert keys_holding(board, lambda c: c["number"] == order.order_number) == ["painter"]


@pytest.mark.django_db
def test_working_order_with_no_production_rows_sits_in_working(order_factory, today, superuser):
    """Rover and Painter are optional — Detailing only creates them when its squares
    are non-zero, so an order with neither must not fall out of the board."""
    order = order_factory(end_date=today + datetime.timedelta(days=30))
    order.status = OrderStatus.WORKING
    order.save(update_fields=["status"])

    board = order_board(user=superuser, show_price=True)

    assert keys_holding(board, lambda c: c["number"] == order.order_number) == ["working"]


@pytest.mark.django_db
def test_order_card_hides_money_without_the_price_permission(order_factory, today, superuser):
    from djmoney.money import Money

    order = order_factory(end_date=today + datetime.timedelta(days=30))
    order.price = Money(100, "USD")
    order.save()  # not update_fields: djmoney stores the currency in its own column

    with_price = column(order_board(user=superuser, show_price=True), "created")["cards"]
    without_price = column(order_board(user=superuser, show_price=False), "created")["cards"]

    assert "total" in with_price[0]
    assert "total" not in without_price[0]


@pytest.mark.django_db
def test_overdue_order_card_is_flagged_danger(order_factory, today, superuser):
    order = order_factory(end_date=today - datetime.timedelta(days=3))
    order.status = OrderStatus.WORKING
    order.save(update_fields=["status"])

    card = column(order_board(user=superuser, show_price=True), "working")["cards"][0]

    assert card["pill_level"] == "danger"
    assert "3" in card["pill_text"]


# --- Замеры -----------------------------------------------------------------


@pytest.mark.django_db
def test_measured_metering_without_a_design_stays_in_the_measured_column(db_client):
    metering = Metering.objects.create(
        client=db_client, date_time=datetime.datetime.now(), status=MeteringStatus.metering_done
    )

    board = metering_board()

    assert keys_holding(board, lambda c: c["client"] == str(metering.client)) == ["measured"]


@pytest.mark.django_db
def test_unfinished_design_moves_the_metering_to_the_design_column(db_client):
    from metering.design.models import Design

    metering = Metering.objects.create(
        client=db_client, date_time=datetime.datetime.now(), status=MeteringStatus.metering_done
    )
    Design.objects.create(metering=metering)

    board = metering_board()

    assert keys_holding(board, lambda c: c["client"] == str(metering.client)) == ["design"]


@pytest.mark.django_db
def test_finished_design_moves_the_metering_to_the_price_column(db_client):
    from metering.design.models import Design

    metering = Metering.objects.create(
        client=db_client, date_time=datetime.datetime.now(), status=MeteringStatus.metering_done
    )
    design = Design.objects.create(metering=metering)
    design.done = True
    design.save(update_fields=["done"])

    board = metering_board()

    assert keys_holding(board, lambda c: c["client"] == str(metering.client)) == ["price"]


# --- Call-center ------------------------------------------------------------


@pytest.mark.django_db
def test_unanswered_invoice_goes_to_the_new_column(db_client):
    invoice = Invoice.objects.create(client=db_client)

    board = call_center_board()

    assert keys_holding(board, lambda c: c["number"] == invoice.pk) == ["new"]


@pytest.mark.django_db
def test_answered_invoice_goes_to_its_solution_column(db_client):
    invoice = Invoice.objects.create(client=db_client, solution=SolutionChoice.re_phone)

    board = call_center_board()

    assert keys_holding(board, lambda c: c["number"] == invoice.pk) == ["re_phone"]


# --- dashboard view ---------------------------------------------------------


@pytest.mark.django_db
def test_dashboard_renders_all_three_boards_for_a_superuser(logged_in_admin_client, order_factory):
    order_factory()

    response = logged_in_admin_client.get(reverse("admin:index"))

    assert response.status_code == 200
    boards = response.context["boards"]
    assert [b["id"] for b in boards] == ["orders", "meterings", "callcenter"]


@pytest.mark.django_db
def test_dashboard_shows_only_the_boards_a_user_may_view(rf, django_user_model):
    from django.contrib.auth.models import Permission

    from core.views import dashboard_callback

    staff = django_user_model.objects.create_user(phone="+998900000301", password="x")
    staff.is_staff = True
    staff.save()
    staff.user_permissions.add(Permission.objects.get(codename="view_invoice"))
    staff = django_user_model.objects.get(pk=staff.pk)  # drop the permission cache

    request = rf.get("/admin/")
    request.user = staff

    context = dashboard_callback(request, {})

    assert [b["id"] for b in context["boards"]] == ["callcenter"]


# --- exhaustive partition ---------------------------------------------------
#
# The single most important property of every board: no record may fall between
# the columns, and none may appear twice. One record per state, then the column
# counts must add up to the table.


@pytest.mark.django_db
def test_every_order_status_is_covered_by_exactly_one_column(order_factory, today, superuser):
    from order.models import Order

    for status in OrderStatus.values:
        order = order_factory(end_date=today + datetime.timedelta(days=30))
        order.status = status
        order.save(update_fields=["status"])

    board = order_board(user=superuser, show_price=True)

    assert sum(col["count"] for col in board) == Order.objects.count() == len(OrderStatus.values)


@pytest.mark.django_db
def test_every_metering_status_is_covered_by_exactly_one_column(db_client):
    for status in MeteringStatus.values:
        Metering.objects.create(
            client=db_client, date_time=datetime.datetime.now(), status=status
        )

    board = metering_board()

    assert sum(col["count"] for col in board) == Metering.objects.count()


@pytest.mark.django_db
def test_every_invoice_solution_is_covered_by_exactly_one_column(db_client):
    Invoice.objects.create(client=db_client)  # unanswered
    for solution in SolutionChoice.values:
        Invoice.objects.create(client=db_client, solution=solution)

    board = call_center_board()

    assert sum(col["count"] for col in board) == Invoice.objects.count()


@pytest.mark.django_db
def test_metering_with_a_finished_design_and_price_still_lands_in_one_column(db_client):
    """The Нарх column is the end of the measured branch — a metering whose price is
    also finished must stay there rather than fall out of the board."""
    from metering.design.models import Design
    from metering.price.models import Price

    metering = Metering.objects.create(
        client=db_client, date_time=datetime.datetime.now(), status=MeteringStatus.metering_done
    )
    design = Design.objects.create(metering=metering)
    design.done = True
    design.save(update_fields=["done"])
    Price.objects.create(metering=metering, done=True)

    board = metering_board()

    assert keys_holding(board, lambda c: c["client"] == str(metering.client)) == ["price"]


# --- assembly scoping -------------------------------------------------------


@pytest.mark.django_db
def test_assembly_columns_are_scoped_to_the_worker_without_the_manager_permission(
    order_factory, today, django_user_model
):
    """AssemblyAdmin.get_queryset shows an assembler only their own jobs, and the
    dashboard this board replaced did the same. Without the manager permission the
    Сборка column must not leak every order."""
    from order.assembly.models import Assembly

    worker = django_user_model.objects.create_user(phone="+998900000401", password="x")
    worker.is_staff = True
    worker.save()

    mine = order_factory(end_date=today + datetime.timedelta(days=10))
    mine.status = OrderStatus.ASSEMBLY
    mine.save(update_fields=["status"])
    Assembly.objects.create(order=mine, square=4, user=worker)

    theirs = order_factory(end_date=today + datetime.timedelta(days=10))
    theirs.status = OrderStatus.ASSEMBLY
    theirs.save(update_fields=["status"])
    Assembly.objects.create(order=theirs, square=4)

    board = order_board(user=worker, show_price=False)

    assert column(board, "assembly")["count"] == 1
    assert [c["number"] for c in column(board, "assembly")["cards"]] == [mine.order_number]


@pytest.mark.django_db
def test_assembly_manager_sees_every_order_in_the_assembly_column(
    order_factory, today, superuser
):
    from order.assembly.models import Assembly

    order = order_factory(end_date=today + datetime.timedelta(days=10))
    order.status = OrderStatus.ASSEMBLY
    order.save(update_fields=["status"])
    Assembly.objects.create(order=order, square=4)

    board = order_board(user=superuser, show_price=False)

    assert column(board, "assembly")["count"] == 1


@pytest.mark.django_db
def test_painter_column_is_scoped_to_the_painter_assigned_to_the_work(
    order_factory, today, django_user_model
):
    """PainterAdmin.get_queryset filters on type__user — a painter is assigned work
    through PainterType — so the Моляр column must narrow the same way."""
    from djmoney.money import Money

    from order.painter.models import Painter, PainterType

    worker = django_user_model.objects.create_user(phone="+998900000402", password="x")
    worker.is_staff = True
    worker.save()
    other = django_user_model.objects.create_user(phone="+998900000403", password="x")

    mine_type = PainterType.objects.create(name="Акрил", price=Money(5, "USD"), user=worker)
    theirs_type = PainterType.objects.create(name="Эмаль", price=Money(5, "USD"), user=other)

    mine = order_factory(end_date=today + datetime.timedelta(days=10))
    mine.status = OrderStatus.WORKING
    mine.save(update_fields=["status"])
    Painter.objects.create(order=mine, square=3, type=mine_type)

    theirs = order_factory(end_date=today + datetime.timedelta(days=10))
    theirs.status = OrderStatus.WORKING
    theirs.save(update_fields=["status"])
    Painter.objects.create(order=theirs, square=3, type=theirs_type)

    board = order_board(user=worker, show_price=False)

    assert column(board, "painter")["count"] == 1
    assert [c["number"] for c in column(board, "painter")["cards"]] == [mine.order_number]


@pytest.mark.django_db
def test_rover_column_is_not_scoped(order_factory, today, django_user_model):
    """RoverAdmin has no per-user filter, so the Ровер column must not invent one."""
    from order.rover.models import Rover

    worker = django_user_model.objects.create_user(phone="+998900000404", password="x")
    worker.is_staff = True
    worker.save()

    order = order_factory(end_date=today + datetime.timedelta(days=10))
    order.status = OrderStatus.WORKING
    order.save(update_fields=["status"])
    Rover.objects.create(order=order, square=3)

    board = order_board(user=worker, show_price=False)

    assert column(board, "rover")["count"] == 1
