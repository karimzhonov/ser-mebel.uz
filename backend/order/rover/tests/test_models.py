import pytest

from order.rover.models import Rover


@pytest.mark.django_db
def test_create_rover_folders_handles_metering_less_order_without_folder(order_factory):
    """Regression test: a metering-less Order can have folder=None (see
    order.models.replace_order_folders' early-return for instance.metering is
    None). create_rover_folders must not crash dereferencing
    instance.order.folder.owner in that case.
    """
    order = order_factory()
    assert order.folder is None

    rover = Rover.objects.create(order=order, square=5)

    assert rover.folder is None
