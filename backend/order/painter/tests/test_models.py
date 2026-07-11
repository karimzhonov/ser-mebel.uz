import pytest

from order.painter.models import Painter


@pytest.mark.django_db
def test_create_painter_folders_handles_metering_less_order_without_folder(order_factory):
    """Regression test: a metering-less Order can have folder=None (see
    order.models.replace_order_folders' early-return for instance.metering is
    None). create_painter_folders must not crash dereferencing
    instance.order.folder.owner in that case.
    """
    order = order_factory()
    assert order.folder is None

    painter = Painter.objects.create(order=order, square=5)

    assert painter.folder is None
