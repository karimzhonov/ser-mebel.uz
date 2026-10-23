import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

BOT_TOKEN = "123456:TEST-TOKEN"


def _init_data(user_id, *, token=BOT_TOKEN, auth_date=None):
    fields = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAH",
        "user": json.dumps({"id": user_id, "first_name": "Ali"}),
    }
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_login_with_phone_and_password_returns_tokens_and_user(make_staff):
    user = make_staff("order.view_order")
    resp = APIClient().post(
        "/api/v1/auth/login/", {"phone": str(user.phone), "password": "pass12345"}, format="json"
    )
    assert resp.status_code == 200, resp.content
    assert resp.data["access"] and resp.data["refresh"]
    assert "order.view_order" in resp.data["user"]["permissions"]


def test_login_refused_for_non_staff(db):
    from oauth.models import User

    User.objects.create_user(phone="+998901234500", password="pass12345")
    resp = APIClient().post(
        "/api/v1/auth/login/", {"phone": "+998901234500", "password": "pass12345"}, format="json"
    )
    assert resp.status_code == 400


def test_api_requires_authentication(db):
    assert APIClient().get("/api/v1/orders/").status_code == 401


def test_me_lists_permissions(api):
    client = api("call_center.view_invoice")
    resp = client.get("/api/v1/auth/me/")
    assert resp.status_code == 200
    assert resp.data["permissions"] == ["call_center.view_invoice"]


def test_telegram_login_accepts_valid_signature(make_staff, settings):
    settings.TELEGRAM_BOT_TOKEN = BOT_TOKEN
    settings.TELEGRAM_WEBAPP_LOGIN_ENABLED = True
    make_staff(telegram_id=777)
    resp = APIClient().post("/api/v1/auth/telegram/", {"init_data": _init_data(777)}, format="json")
    assert resp.status_code == 200, resp.content
    assert resp.data["access"]


def test_telegram_login_rejects_forged_signature(make_staff, settings):
    settings.TELEGRAM_BOT_TOKEN = BOT_TOKEN
    settings.TELEGRAM_WEBAPP_LOGIN_ENABLED = True
    make_staff(telegram_id=777)
    forged = _init_data(777, token="999:OTHER-BOT")
    resp = APIClient().post("/api/v1/auth/telegram/", {"init_data": forged}, format="json")
    assert resp.status_code == 401


def test_telegram_login_rejects_tampered_user_id(make_staff, settings):
    settings.TELEGRAM_BOT_TOKEN = BOT_TOKEN
    settings.TELEGRAM_WEBAPP_LOGIN_ENABLED = True
    make_staff(telegram_id=777)
    make_staff(telegram_id=888)
    data = _init_data(777).replace("777", "888")
    resp = APIClient().post("/api/v1/auth/telegram/", {"init_data": data}, format="json")
    assert resp.status_code == 401


def test_telegram_login_rejects_stale_payload(make_staff, settings):
    settings.TELEGRAM_BOT_TOKEN = BOT_TOKEN
    settings.TELEGRAM_WEBAPP_LOGIN_ENABLED = True
    settings.TELEGRAM_INIT_DATA_MAX_AGE = 60
    make_staff(telegram_id=777)
    old = _init_data(777, auth_date=int(time.time()) - 3600)
    resp = APIClient().post("/api/v1/auth/telegram/", {"init_data": old}, format="json")
    assert resp.status_code == 401


def test_telegram_login_unknown_user_forbidden(db, settings):
    settings.TELEGRAM_BOT_TOKEN = BOT_TOKEN
    settings.TELEGRAM_WEBAPP_LOGIN_ENABLED = True
    resp = APIClient().post("/api/v1/auth/telegram/", {"init_data": _init_data(555)}, format="json")
    assert resp.status_code == 403


def test_telegram_login_disabled_by_default(make_staff, settings):
    settings.TELEGRAM_BOT_TOKEN = BOT_TOKEN
    settings.TELEGRAM_WEBAPP_LOGIN_ENABLED = False
    make_staff(telegram_id=777)
    resp = APIClient().post("/api/v1/auth/telegram/", {"init_data": _init_data(777)}, format="json")
    assert resp.status_code == 404


def test_telegram_login_never_for_superuser(make_staff, settings):
    settings.TELEGRAM_BOT_TOKEN = BOT_TOKEN
    settings.TELEGRAM_WEBAPP_LOGIN_ENABLED = True
    make_staff(superuser=True, telegram_id=777)
    resp = APIClient().post("/api/v1/auth/telegram/", {"init_data": _init_data(777)}, format="json")
    assert resp.status_code == 403


def test_logout_blacklists_refresh_token(make_staff):
    user = make_staff()
    client = APIClient()
    tokens = client.post(
        "/api/v1/auth/login/", {"phone": str(user.phone), "password": "pass12345"}, format="json"
    ).data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    assert (
        client.post(
            "/api/v1/auth/logout/", {"refresh": tokens["refresh"]}, format="json"
        ).status_code
        == 204
    )
    resp = APIClient().post("/api/v1/auth/refresh/", {"refresh": tokens["refresh"]}, format="json")
    assert resp.status_code == 401
