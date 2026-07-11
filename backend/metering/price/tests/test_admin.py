import datetime

import pytest
from django.contrib import admin
from djmoney.money import Money

from metering.price.admin import MeteringPresenceFilter, PriceAdmin
from metering.price.models import Price
from order.models import Order


class _FakeForm:
    """Just enough of a ModelForm to satisfy ModelAdmin.save_related(): it only
    calls form.save_m2m() and reads form.instance."""

    def __init__(self, instance):
        self.instance = instance

    def save_m2m(self):
        pass


@pytest.mark.django_db
def test_price_save_related_null_metering_does_not_touch_other_orders(db_client, today):
    """Regression: PriceAdmin.save_related used to run
    Order.objects.filter(metering=obj.metering).update(...) unconditionally.
    When obj.metering was None, that filter matched *every* metering-less
    order and overwrote their prices. The guard `if obj.metering:` must stop
    that from happening.
    """
    unrelated_order = Order.objects.create(
        client=db_client,
        reception_date=today,
        address="addr",
        metering=None,
        price=Money(100, "USD"),
    )

    price_without_metering = Price.objects.create(metering=None)

    price_admin = PriceAdmin(Price, admin.site)
    form = _FakeForm(price_without_metering)

    # No inline formsets needed to exercise the guard.
    price_admin.save_related(request=None, form=form, formsets=[], change=False)

    unrelated_order.refresh_from_db()
    assert unrelated_order.price == Money(100, "USD"), (
        "save_related() with a metering-less Price must not mutate the price of "
        "an unrelated metering-less Order."
    )


@pytest.mark.django_db
def test_price_save_related_updates_own_metering_order(db_client, today):
    """Sanity check the opposite path still works: when the Price *does* have a
    metering, its linked Order price is updated."""
    from metering.design.models import Design
    from metering.models import Metering

    metering = Metering.objects.create(
        client=db_client,
        date_time=datetime.datetime.now(),
    )
    Design.objects.create(metering=metering)
    order = Order.objects.create(
        client=db_client,
        reception_date=today,
        address="addr",
        metering=metering,
        price=Money(0, "USD"),
    )

    price = Price.objects.create(metering=metering)
    price_admin = PriceAdmin(Price, admin.site)
    form = _FakeForm(price)

    price_admin.save_related(request=None, form=form, formsets=[], change=False)

    order.refresh_from_db()
    assert order.price == Money(0, "USD")


@pytest.mark.django_db
def test_create_price_without_metering_via_orm_succeeds():
    price = Price.objects.create(metering=None)
    assert price.pk is not None
    assert price.metering is None


@pytest.mark.django_db
def test_create_price_without_metering_via_admin_add_view(logged_in_admin_client):
    from django.urls import reverse

    url = reverse("admin:price_price_add")
    response = logged_in_admin_client.post(url, data={"desc": "no metering price"}, follow=True)

    assert response.status_code == 200
    assert Price.objects.filter(desc="no metering price", metering=None).exists()


@pytest.mark.django_db
def test_price_metering_presence_filter(rf, db_client):
    from metering.models import Metering

    metering = Metering.objects.create(client=db_client, date_time=datetime.datetime.now())
    price_with_metering = Price.objects.create(metering=metering)
    price_without_metering = Price.objects.create(metering=None)

    price_admin = PriceAdmin(Price, admin.site)

    # Mirror how ChangeList actually builds these: a real QueryDict, whose
    # .pop() returns a list (SimpleListFilter.__init__ does `value[-1]`).
    request_yes = rf.get("/", {"has_metering": "yes"})
    f = MeteringPresenceFilter(request_yes, request_yes.GET.copy(), Price, price_admin)
    qs_yes = f.queryset(request_yes, Price.objects.all())
    assert list(qs_yes) == [price_with_metering]

    request_no = rf.get("/", {"has_metering": "no"})
    f_no = MeteringPresenceFilter(request_no, request_no.GET.copy(), Price, price_admin)
    qs_no = f_no.queryset(request_no, Price.objects.all())
    assert list(qs_no) == [price_without_metering]


@pytest.mark.django_db
def test_metering_folder_display_guards_null_metering():
    price_admin = PriceAdmin(Price, admin.site)
    price = Price.objects.create(metering=None)

    result = price_admin.metering_folder(price)  # must not raise AttributeError

    assert result == "-"
