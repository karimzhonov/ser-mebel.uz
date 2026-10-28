import json
from unittest import mock

import pytest
from django.test import Client

from core.bot_signing import HEADER_ACTOR, HEADER_NONCE, HEADER_SIG, HEADER_TS, verify
from oauth.models import User


@pytest.mark.django_db
def test_telegram_id_query_no_longer_logs_in():
    User.objects.create_user(phone="+998900000010", password="x", telegram_id=4242, is_staff=True)
    c = Client()
    r = c.get("/?telegram_id=4242")
    assert r.status_code == 404
    assert "_auth_user_id" not in c.session


@pytest.mark.django_db
def test_send_message_is_signed(settings):
    settings.TELEGRAM_BOT_TOKEN = "123:abc"
    user = User.objects.create_user(phone="+998900000011", password="x", telegram_id=55)
    with mock.patch("oauth.models.requests.post") as post:
        user.send_message(url="/orders/1", text="Salom")
    url = post.call_args.args[0]
    body = post.call_args.kwargs["data"]
    h = post.call_args.kwargs["headers"]
    assert url.endswith("/user/55/message")
    assert json.loads(body) == {"text": "Salom", "url": "/orders/1"}
    assert verify(
        h[HEADER_SIG],
        h[HEADER_TS],
        "POST",
        "/user/55/message",
        h[HEADER_ACTOR],
        body,
        nonce=h[HEADER_NONCE],
    )


@pytest.mark.django_db
def test_admin_login_page_renders_for_anonymous():
    assert Client().get("/admin/login/?next=/admin/").status_code == 200
