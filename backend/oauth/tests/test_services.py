from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from oauth.services import notify_staff, staff_with_permission


def _make_user(phone, name="", **extra):
    from oauth.models import User

    user = User(phone=phone, name=name, is_staff=True, **extra)
    user.set_password("pass12345")
    user.save()
    return user


@pytest.fixture
def user_content_type():
    from oauth.models import User

    return ContentType.objects.get_for_model(User)


@pytest.fixture
def perm(user_content_type):
    return Permission.objects.create(
        codename="test_notify_perm", name="Test notify perm", content_type=user_content_type
    )


# ---------------------------------------------------------------------------
# staff_with_permission
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_direct_and_group_permission_dedup(perm):
    """A user holding the same permission both directly AND via a group must
    appear exactly once — tests the .distinct() in staff_with_permission."""
    user = _make_user("+998901000001", name="Both")
    user.user_permissions.add(perm)
    group = Group.objects.create(name="grp-both")
    group.permissions.add(perm)
    user.groups.add(group)

    result = list(staff_with_permission(perm.codename))

    assert [u.pk for u in result].count(user.pk) == 1


@pytest.mark.django_db
def test_staff_with_permission_only_returns_matching_users(perm):
    matching = _make_user("+998901000002", name="Match")
    matching.user_permissions.add(perm)
    _make_user("+998901000003", name="NoMatch")

    result = list(staff_with_permission(perm.codename))

    assert result == [matching]


@pytest.mark.django_db
def test_staff_with_permission_via_group_only(perm):
    user = _make_user("+998901000004", name="GroupOnly")
    group = Group.objects.create(name="grp-only")
    group.permissions.add(perm)
    user.groups.add(group)

    result = list(staff_with_permission(perm.codename))

    assert result == [user]


# ---------------------------------------------------------------------------
# notify_staff
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_notify_staff_sends_telegram_to_all_matching_users_regardless_of_phone(perm):
    with_phone = _make_user("+998901000010", name="WithPhone")
    with_phone.user_permissions.add(perm)
    no_phone = _make_user("", name="NoPhone")
    no_phone.user_permissions.add(perm)

    with (
        patch("oauth.models.User.send_message") as mock_send,
        patch("oauth.services.send_bulk_sms") as mock_bulk,
    ):
        notify_staff(
            permission=f"oauth.{perm.codename}",
            path_name="admin:order_order_change",
            kwargs={"object_id": 1},
            telegram_text="hello",
        )

    assert mock_send.call_count == 2
    mock_bulk.assert_called_once_with([])


@pytest.mark.django_db
def test_notify_staff_excludes_user_without_phone_from_sms_batch(perm):
    with_phone = _make_user("+998901000011", name="WithPhone")
    with_phone.user_permissions.add(perm)
    no_phone = _make_user("", name="NoPhone")
    no_phone.user_permissions.add(perm)

    with (
        patch("oauth.models.User.send_message"),
        patch("oauth.services.send_bulk_sms") as mock_bulk,
    ):
        notify_staff(
            permission=perm.codename,
            path_name="admin:order_order_change",
            kwargs={"object_id": 1},
            sms_template="{xodim_ism}, hi\n{url}",
        )

    batch = mock_bulk.call_args.args[0]
    assert len(batch) == 1
    assert batch[0]["phone"] == "998901000011"


@pytest.mark.django_db
def test_notify_staff_without_sms_template_sends_empty_batch(perm):
    user = _make_user("+998901000012", name="U")
    user.user_permissions.add(perm)

    with (
        patch("oauth.models.User.send_message"),
        patch("oauth.services.send_bulk_sms") as mock_bulk,
    ):
        notify_staff(
            permission=perm.codename,
            path_name="admin:order_order_change",
            kwargs={"object_id": 1},
        )

    mock_bulk.assert_called_once_with([])


@pytest.mark.django_db
def test_notify_staff_xodim_ism_varies_per_recipient(perm):
    alice = _make_user("+998901000013", name="Alice")
    alice.user_permissions.add(perm)
    bob = _make_user("+998901000014", name="Bob")
    bob.user_permissions.add(perm)

    with (
        patch("oauth.models.User.send_message"),
        patch("oauth.services.send_bulk_sms") as mock_bulk,
    ):
        notify_staff(
            permission=perm.codename,
            path_name="admin:order_order_change",
            kwargs={"object_id": 1},
            sms_template="{xodim_ism}, hi\n{url}",
        )

    batch = mock_bulk.call_args.args[0]
    texts_by_phone = {item["phone"]: item["text"] for item in batch}
    assert texts_by_phone["998901000013"].startswith("Alice,")
    assert texts_by_phone["998901000014"].startswith("Bob,")
    assert texts_by_phone["998901000013"] != texts_by_phone["998901000014"]


@pytest.mark.django_db
def test_notify_staff_bare_and_dotted_codename_resolve_same_recipients(perm):
    user = _make_user("+998901000015", name="U")
    user.user_permissions.add(perm)

    with patch("oauth.models.User.send_message") as mock_send_bare:
        notify_staff(
            permission=perm.codename,
            path_name="admin:order_order_change",
            kwargs={"object_id": 1},
        )
        bare_calls = mock_send_bare.call_count

    with patch("oauth.models.User.send_message") as mock_send_dotted:
        notify_staff(
            permission=f"oauth.{perm.codename}",
            path_name="admin:order_order_change",
            kwargs={"object_id": 1},
        )
        dotted_calls = mock_send_dotted.call_count

    assert bare_calls == dotted_calls == 1


@pytest.mark.django_db
def test_notify_staff_sms_context_value_with_braces_does_not_crash(perm):
    """A dynamic value (e.g. a client's free-text name) must go through
    sms_context, not be embedded directly into the template string — a value
    containing literal braces must not raise from .format()."""
    user = _make_user("+998901000017", name="U")
    user.user_permissions.add(perm)

    with (
        patch("oauth.models.User.send_message"),
        patch("oauth.services.send_bulk_sms") as mock_bulk,
    ):
        notify_staff(
            permission=perm.codename,
            path_name="admin:order_order_change",
            kwargs={"object_id": 1},
            sms_template="{xodim_ism}, {mijoz_ism} dizayni tayyor\n{url}",
            sms_context={"mijoz_ism": "{Client} & Co {oops}"},
        )

    batch = mock_bulk.call_args.args[0]
    assert "{Client} & Co {oops}" in batch[0]["text"]


@pytest.mark.django_db
def test_notify_staff_telegram_false_skips_send_message(perm):
    user = _make_user("+998901000016", name="U")
    user.user_permissions.add(perm)

    with (
        patch("oauth.models.User.send_message") as mock_send,
        patch("oauth.services.send_bulk_sms"),
    ):
        notify_staff(
            permission=perm.codename,
            path_name="admin:order_order_change",
            kwargs={"object_id": 1},
            telegram=False,
        )

    mock_send.assert_not_called()
