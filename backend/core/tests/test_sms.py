import json
from unittest.mock import Mock, patch

import pytest
import requests
from django.test import override_settings

from core.sms import absolute_url, format_phone, send_bulk_sms

# ---------------------------------------------------------------------------
# format_phone
# ---------------------------------------------------------------------------


def test_format_phone_none_returns_none():
    assert format_phone(None) is None


def test_format_phone_empty_string_returns_none():
    assert format_phone("") is None


def test_format_phone_usable_phone_returns_digits_no_plus():
    from phonenumber_field.phonenumber import PhoneNumber

    phone = PhoneNumber.from_string("+998901234567")

    result = format_phone(phone)

    assert result == "998901234567"
    assert not result.startswith("+")


def test_format_phone_malformed_object_returns_none_without_raising():
    """A truthy value that doesn't behave like a PhoneNumber (no .as_e164)
    must be swallowed, not raised."""
    result = format_phone("not-a-phone-object")

    assert result is None


def test_format_phone_object_raising_on_as_e164_returns_none():
    class Explode:
        def __bool__(self):
            return True

        @property
        def as_e164(self):
            raise ValueError("boom")

    assert format_phone(Explode()) is None


# ---------------------------------------------------------------------------
# absolute_url
# ---------------------------------------------------------------------------


@override_settings(ADMIN_BASE_URL=None)
def test_absolute_url_without_base_returns_path_unchanged():
    assert absolute_url("/admin/order/order/1/change/") == "/admin/order/order/1/change/"


@override_settings(ADMIN_BASE_URL="https://admin.example.com")
def test_absolute_url_prepends_base():
    assert (
        absolute_url("/admin/order/order/1/change/")
        == "https://admin.example.com/admin/order/order/1/change/"
    )


@override_settings(ADMIN_BASE_URL="https://admin.example.com/")
def test_absolute_url_strips_trailing_slash_on_base():
    assert (
        absolute_url("/admin/order/order/1/change/")
        == "https://admin.example.com/admin/order/order/1/change/"
    )


# ---------------------------------------------------------------------------
# send_bulk_sms
# ---------------------------------------------------------------------------


def _ok_response(body=None):
    resp = Mock()
    resp.json.return_value = body if body is not None else []
    resp.text = json.dumps(body if body is not None else [])
    return resp


@override_settings(
    SMS_LOGIN="test-login",
    SMS_PASSWORD="test-pass",
    SMS_GATEWAY_URL="http://gateway.test/smsgateway/",
    SMS_NICKNAME=None,
)
@patch("core.sms.requests.post")
def test_send_bulk_sms_empty_list_makes_no_http_call(mock_post):
    send_bulk_sms([])

    mock_post.assert_not_called()


@override_settings(SMS_LOGIN=None)
@patch("core.sms.requests.post")
def test_send_bulk_sms_no_login_makes_no_http_call_even_with_messages(mock_post):
    send_bulk_sms([{"phone": "998901234567", "text": "hi"}])

    mock_post.assert_not_called()


@override_settings(
    SMS_LOGIN="test-login",
    SMS_PASSWORD="test-pass",
    SMS_GATEWAY_URL="http://gateway.test/smsgateway/",
    SMS_NICKNAME=None,
)
@patch("core.sms.requests.post")
def test_send_bulk_sms_chunks_over_100_into_multiple_posts(mock_post):
    mock_post.return_value = _ok_response([])
    messages = [{"phone": f"99890000{i:04d}", "text": f"msg {i}"} for i in range(150)]

    send_bulk_sms(messages)

    assert mock_post.call_count == 2
    chunk_sizes = []
    for call in mock_post.call_args_list:
        payload = call.kwargs["data"]
        chunk = json.loads(payload["data"])
        chunk_sizes.append(len(chunk))
        assert len(chunk) <= 100
    assert chunk_sizes == [100, 50]


@override_settings(
    SMS_LOGIN="test-login",
    SMS_PASSWORD="test-pass",
    SMS_GATEWAY_URL="http://gateway.test/smsgateway/",
    SMS_NICKNAME=None,
)
@patch("core.sms.requests.post")
def test_send_bulk_sms_sends_form_encoded_data_not_json(mock_post):
    mock_post.return_value = _ok_response([])

    send_bulk_sms([{"phone": "998901234567", "text": "hi"}])

    mock_post.assert_called_once()
    call = mock_post.call_args
    assert "data" in call.kwargs
    assert "json" not in call.kwargs
    assert call.kwargs["data"]["login"] == "test-login"
    assert call.kwargs["data"]["password"] == "test-pass"


@override_settings(
    SMS_LOGIN="test-login",
    SMS_PASSWORD="test-pass",
    SMS_GATEWAY_URL="http://gateway.test/smsgateway/",
    SMS_NICKNAME=None,
)
@patch("core.sms.requests.post")
def test_send_bulk_sms_swallows_request_exception(mock_post):
    mock_post.side_effect = requests.RequestException("connection refused")

    # Must not raise.
    send_bulk_sms([{"phone": "998901234567", "text": "hi"}])

    mock_post.assert_called_once()


@override_settings(
    SMS_LOGIN="test-login",
    SMS_PASSWORD="test-pass",
    SMS_GATEWAY_URL="http://gateway.test/smsgateway/",
    SMS_NICKNAME=None,
)
@patch("core.sms.requests.post")
def test_send_bulk_sms_handles_global_auth_error_response(mock_post, caplog):
    mock_post.return_value = _ok_response(
        [{"error": 1, "error_no": 101, "text": "Invalid login/password"}]
    )

    with caplog.at_level("WARNING"):
        send_bulk_sms([{"phone": "998901234567", "text": "hi"}])

    assert any("101" in r.getMessage() for r in caplog.records)
    assert any("Invalid login/password" in r.getMessage() for r in caplog.records)


@override_settings(
    SMS_LOGIN="test-login",
    SMS_PASSWORD="test-pass",
    SMS_GATEWAY_URL="http://gateway.test/smsgateway/",
    SMS_NICKNAME=None,
)
@patch("core.sms.requests.post")
def test_send_bulk_sms_handles_per_recipient_error_response(mock_post, caplog):
    mock_post.return_value = _ok_response(
        [
            {
                "error": 1,
                "error_no": 300,
                "error_text": "Bad number",
                "recipient": "998901234567",
            }
        ]
    )

    with caplog.at_level("WARNING"):
        send_bulk_sms([{"phone": "998901234567", "text": "hi"}])

    assert any("Bad number" in r.getMessage() for r in caplog.records)
    assert any("998901234567" in r.getMessage() for r in caplog.records)


@override_settings(
    SMS_LOGIN="test-login",
    SMS_PASSWORD="test-pass",
    SMS_GATEWAY_URL="http://gateway.test/smsgateway/",
    SMS_NICKNAME=None,
)
@patch("core.sms.requests.post")
def test_send_bulk_sms_handles_global_auth_error_as_bare_dict(mock_post, caplog):
    """Global auth/limit errors can come back as a single object, not list-wrapped."""
    mock_post.return_value = _ok_response(
        {"error": 1, "error_no": 101, "text": "Incorrect Login or Password"}
    )

    with caplog.at_level("WARNING"):
        send_bulk_sms([{"phone": "998901234567", "text": "hi"}])

    assert any("101" in r.getMessage() for r in caplog.records)
    assert any("Incorrect Login or Password" in r.getMessage() for r in caplog.records)


@override_settings(
    SMS_LOGIN="test-login",
    SMS_PASSWORD="test-pass",
    SMS_GATEWAY_URL="http://gateway.test/smsgateway/",
    SMS_NICKNAME=None,
)
@patch("core.sms.requests.post")
def test_send_bulk_sms_handles_non_json_response(mock_post, caplog):
    resp = Mock()
    resp.json.side_effect = ValueError("not json")
    resp.text = "<html>502 Bad Gateway</html>"
    mock_post.return_value = resp

    with caplog.at_level("WARNING"):
        # Must not raise.
        send_bulk_sms([{"phone": "998901234567", "text": "hi"}])

    assert any("non-JSON" in r.getMessage() for r in caplog.records)


@override_settings(
    SMS_LOGIN="test-login",
    SMS_PASSWORD="test-pass",
    SMS_GATEWAY_URL="http://gateway.test/smsgateway/",
    SMS_NICKNAME="MyBrand",
)
@patch("core.sms.requests.post")
def test_send_bulk_sms_includes_nickname_when_set(mock_post):
    mock_post.return_value = _ok_response([])

    send_bulk_sms([{"phone": "998901234567", "text": "hi"}])

    assert mock_post.call_args.kwargs["data"]["nickname"] == "MyBrand"
