import pytest

from order.detailing.models import Detailing


@pytest.mark.django_db
def test_create_detailing_folders_handles_metering_less_order_without_folder(order_factory):
    """Regression test: a metering-less Order can have folder=None (see
    order.models.replace_order_folders' early-return for instance.metering is
    None). create_detailing_folders must not crash dereferencing
    instance.order.folder.owner in that case.
    """
    order = order_factory()
    assert order.folder is None

    detailing = Detailing.objects.create(order=order, square=0)

    assert detailing.folder is None


@pytest.mark.django_db
def test_detailing_with_zero_square_still_creates_an_assembly(order_factory):
    """Previously the Assembly was only created when Detailing.square was non-zero,
    so an order detailed with square=0 reached "Отправить в сборку" with nothing to
    redirect to (the order-40 crash). Every detailed order must now have one.
    """
    from order.assembly.models import Assembly

    order = order_factory()

    Detailing.objects.create(order=order, square=0)

    assembly = Assembly.objects.get(order=order)
    assert assembly.square == 0


@pytest.mark.django_db
def test_zero_square_does_not_overwrite_a_hand_entered_assembly(order_factory):
    """A later Detailing save with square=0 uses get_or_create, so it must leave an
    Assembly whose square was set by hand alone."""
    from djmoney.money import Money

    from order.assembly.models import Assembly

    order = order_factory()
    detailing = Detailing.objects.create(order=order, square=0)

    assembly = Assembly.objects.get(order=order)
    assembly.square = 12.5
    assembly.price = Money(500, "USD")
    assembly.save(update_fields=["square", "price"])

    detailing.save()

    assembly.refresh_from_db()
    assert assembly.square == 12.5
    assert assembly.price == Money(500, "USD")


@pytest.mark.django_db
def test_non_zero_square_still_syncs_the_assembly(order_factory):
    from order.assembly.models import Assembly

    order = order_factory()
    detailing = Detailing.objects.create(order=order, square=0)

    detailing.square = 8
    detailing.save()

    assembly = Assembly.objects.get(order=order)
    assert assembly.square == 8
