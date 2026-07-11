import datetime

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model

from order.assembly.admin import AssemblyAdmin
from order.assembly.constants import ASSEMBLY_MANAGER_PERMISSION
from order.assembly.models import Assembly
from order.models import Order


@pytest.fixture
def assembly_perm():
    from django.contrib.contenttypes.models import ContentType

    content_type = ContentType.objects.get_for_model(Assembly)
    from django.contrib.auth.models import Permission

    perm, _ = Permission.objects.get_or_create(
        codename=ASSEMBLY_MANAGER_PERMISSION,
        content_type=content_type,
        defaults={"name": "Assembly manager"},
    )
    return perm


@pytest.fixture
def manager_user(db, assembly_perm):
    User = get_user_model()
    user = User.objects.create_user(phone="+998900000001", password="pass12345")
    user.is_staff = True
    user.save()
    user.user_permissions.add(assembly_perm)
    return user


@pytest.fixture
def non_manager_user(db):
    User = get_user_model()
    user = User.objects.create_user(phone="+998900000002", password="pass12345")
    user.is_staff = True
    user.save()
    return user


def _order_with_folder(db_client, today):
    """Assembly's own (pre-existing, unrelated) post_save signal dereferences
    order.folder.owner, so give the order a real folder — metering-less orders
    don't get one automatically (see order/models.py replace_order_folders).
    """
    from filer.models.foldermodels import Folder

    order = Order.objects.create(
        client=db_client,
        reception_date=today,
        address="addr",
    )
    order.folder = Folder.objects.create(name=f"order-{order.pk}-folder")
    order.save(update_fields=["folder"])
    return order


@pytest.fixture
def done_assembly(db_client, today):
    order = _order_with_folder(db_client, today)
    return Assembly.objects.create(order=order, square=10, done=True)


@pytest.mark.django_db
def test_manager_can_change_done_assembly(rf, manager_user, done_assembly):
    request = rf.get("/")
    request.user = manager_user

    assembly_admin = AssemblyAdmin(Assembly, admin.site)

    assert assembly_admin.has_change_permission(request, done_assembly) is True


@pytest.mark.django_db
def test_non_manager_cannot_change_done_assembly(rf, non_manager_user, done_assembly):
    request = rf.get("/")
    request.user = non_manager_user

    assembly_admin = AssemblyAdmin(Assembly, admin.site)

    assert assembly_admin.has_change_permission(request, done_assembly) is False


@pytest.mark.django_db
def test_non_manager_cannot_change_not_done_assembly_either(rf, non_manager_user, db_client, today):
    """Unchanged behavior: non-managers can't change assemblies at all, done or not."""
    order = _order_with_folder(db_client, today)
    not_done_assembly = Assembly.objects.create(order=order, square=5, done=False)

    request = rf.get("/")
    request.user = non_manager_user

    assembly_admin = AssemblyAdmin(Assembly, admin.site)

    assert assembly_admin.has_change_permission(request, not_done_assembly) is False
