import datetime
import io

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory


@pytest.fixture(autouse=True)
def _converted_cost_manager_request():
    """core.djmoney.ConvertedCostManager.request is a *class*-level attribute
    set by ConvertedCostMiddleware on every real HTTP request/response cycle
    and otherwise simply doesn't exist. Any test that hits a
    ConvertedCostManager-backed manager (Calculate, Inventory, ...) without
    going through the Django test client (e.g. calling an admin method
    directly) would otherwise AttributeError — and whether it does depends on
    test *ordering* (whichever earlier test happened to make an HTTP request
    first). Pin it explicitly so tests are deterministic regardless of order.
    """
    from core.djmoney import ConvertedCostManager

    ConvertedCostManager.request = None
    yield
    ConvertedCostManager.request = None


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def admin_site():
    return AdminSite()


@pytest.fixture
def db_client():
    """A client.Client row (named db_client to avoid clashing with Django's test `client` fixture)."""
    from client.models import Client

    return Client.objects.create(phone="+998901234567", fio="Test Client")


@pytest.fixture
def superuser(db):
    User = get_user_model()
    return User.objects.create_superuser(phone="+998901112233", password="pass12345")


@pytest.fixture
def logged_in_admin_client(client, superuser):
    client.force_login(superuser)
    return client


@pytest.fixture
def today():
    return datetime.date.today()


def make_order(*, db_client, reception_date=None, end_date=None, count_days=1, metering=None, price=None, address="Test address"):
    from order.models import Order

    return Order.objects.create(
        client=db_client,
        reception_date=reception_date or datetime.date.today(),
        end_date=end_date,
        count_days=count_days,
        address=address,
        metering=metering,
        price=price,
    )


@pytest.fixture
def order_factory(db_client):
    def _factory(**kwargs):
        kwargs.setdefault("db_client", db_client)
        return make_order(**kwargs)

    return _factory


@pytest.fixture
def png_upload():
    """A minimal, real, valid PNG file suitable for filer.models.Image."""

    def _factory(name="pic.png"):
        from PIL import Image as PILImage

        buf = io.BytesIO()
        PILImage.new("RGB", (10, 10), color="red").save(buf, format="PNG")
        buf.seek(0)
        return SimpleUploadedFile(name, buf.read(), content_type="image/png")

    return _factory
