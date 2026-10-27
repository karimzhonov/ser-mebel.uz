"""Signature auth of /api/v1/bot/ and the shared test vector."""

import pytest

from api.tests.botkit import CONTRACT_DIR, TEST_TOKEN
from core import bot_signing
from core.telegram import link_token, parse_link_token

pytestmark = pytest.mark.django_db

VECTOR = "83d92a6128667c919f544b898f4894caae20cb08ed1c7af9452b8202ace3dd3d"


def test_signing_vector_matches_contract_doc():
    got = bot_signing.sign(
        1700000000,
        "POST",
        "/api/v1/bot/whoami/",
        42,
        b'{"a":1}',
        token="123456:TEST-BOT-TOKEN",
        nonce="0123456789abcdef0123456789abcdef",
    )
    assert got == VECTOR
    if not (CONTRACT_DIR.parent / "BOT_CONTRACT.md").exists():
        pytest.skip("docs/ is not available (mount ./docs at /docs)")
    doc = (CONTRACT_DIR.parent / "BOT_CONTRACT.md").read_text(encoding="utf-8")
    assert VECTOR in doc and "123456:TEST-BOT-TOKEN" in doc


def test_verify_window_and_tamper():
    args = ("POST", "/x/", 7, b"body")
    sig = bot_signing.sign(1000, *args, token=TEST_TOKEN)
    assert bot_signing.verify(sig, 1000, *args, token=TEST_TOKEN, now=1000 + 300)
    assert not bot_signing.verify(sig, 1000, *args, token=TEST_TOKEN, now=1000 + 301)
    assert not bot_signing.verify(sig, 1000, *args, token=TEST_TOKEN, now=1000 - 301)
    assert not bot_signing.verify(sig, 1000, "POST", "/x/", 8, b"body", token=TEST_TOKEN, now=1000)
    assert not bot_signing.verify(sig, 1000, "POST", "/x/", 7, b"body2", token=TEST_TOKEN, now=1000)
    assert not bot_signing.verify("", 1000, *args, token=TEST_TOKEN, now=1000)
    assert not bot_signing.verify(sig, "abc", *args, token=TEST_TOKEN, now=1000)


def test_valid_signature_is_accepted(bot_client, members):
    r = bot_client.get("finance/config/", actor=200)
    assert r.status_code == 200, r.content
    assert set(r.data) == {"channel_id", "usd_rate", "usd_rate_manual", "ready_days", "version"}


@pytest.mark.parametrize(
    "tamper",
    [
        {"tamper_body": True},
        {"actor_header": 100},  # signed for 200, claims to be the boss
        {"ts_offset": -301},
        {"ts_offset": 301},
    ],
)
def test_bad_signature_is_403(bot_client, members, tamper):
    r = bot_client.post("whoami/", actor=200, data={"user": {"id": 200}}, **tamper)
    assert r.status_code == 403


def test_missing_signature_and_jwt_alone_are_403(bot_client, members, api):
    assert bot_client.http.get("/api/v1/bot/finance/config/").status_code == 403
    c = api(superuser=True)  # a valid JWT-style login is not the bot
    assert c.get("/api/v1/bot/finance/config/").status_code == 403
    assert c.post("/api/v1/bot/whoami/", {"user": {"id": 1}}, format="json").status_code == 403


def test_wrong_token_is_403(bot_client, members):
    bot_client.token = "999:OTHER"
    assert bot_client.get("finance/config/", actor=200).status_code == 403


def test_unconfigured_token_never_authenticates(bot_client, settings, members):
    settings.TELEGRAM_BOT_TOKEN = None
    bot_client.token = ""
    assert bot_client.get("finance/config/", actor=200).status_code == 403


def test_bot_endpoints_are_not_in_the_api_docs(admin_api):
    r = admin_api.get("/api/schema/")
    assert r.status_code == 200
    body = r.content.decode()
    assert "/api/v1/orders/" in body and "/bot/" not in body


def test_unknown_actor_cannot_do_member_things(bot_client, members):
    assert bot_client.get("finance/config/", actor=9999).status_code == 403
    assert bot_client.get("finance/config/", actor=None).status_code == 403


def test_link_token_roundtrip_and_tamper(settings):
    t = link_token(5)
    assert t.startswith("u5_") and len(t.rsplit("_", 1)[1]) == 10
    assert parse_link_token(t) == 5
    assert parse_link_token("u5_0000000000") is None
    assert parse_link_token(t.replace("u5_", "u6_")) is None
    assert parse_link_token("u5_" + "G" * 10) is None
    assert parse_link_token("abc") is None
    assert parse_link_token("") is None
    settings.SECRET_KEY = "another"
    assert parse_link_token(t) is None


def test_plain_digits_are_deprecated_but_accepted(caplog):
    with caplog.at_level("WARNING", logger="core.telegram"):
        assert parse_link_token("15") == 15
    assert "deprecated" in caplog.text


def test_me_serializer_telegram_link_is_signed(api):
    c = api()
    link = c.get("/api/v1/auth/me/").data["telegram_link"]
    assert f"?start=u{c.user.pk}_" in link
    assert parse_link_token(link.split("start=")[1]) == c.user.pk


def test_link_endpoint(bot_client, make_staff):
    user = make_staff()
    ok = bot_client.post("link/", data={"token": link_token(user.pk), "telegram_id": 777})
    assert ok.status_code == 200 and ok.data["linked"] is True and ok.data["user"]["id"] == user.pk
    user.refresh_from_db()
    assert user.telegram_id == 777
    for token in ("u%d_0000000000" % user.pk, "u99999_aaaaaaaaaa", "zzz"):
        assert bot_client.post("link/", data={"token": token, "telegram_id": 1}).status_code == 404
    # plain digits still work for one release
    from oauth.models import User

    other = User.objects.create_user(phone="+998900000003", password="x")
    assert (
        bot_client.post("link/", data={"token": str(other.pk), "telegram_id": 778}).status_code
        == 200
    )
    # the Telegram id moves instead of ending up on two users
    assert (
        bot_client.post(
            "link/", data={"token": link_token(other.pk), "telegram_id": 777}
        ).status_code
        == 200
    )
    user.refresh_from_db()
    assert user.telegram_id is None
