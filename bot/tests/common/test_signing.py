from bot.backend.signing import sign, verify

TOKEN = "123456:TEST-BOT-TOKEN"
NONCE = "0123456789abcdef0123456789abcdef"
VECTOR = "83d92a6128667c919f544b898f4894caae20cb08ed1c7af9452b8202ace3dd3d"


def test_vector():
    assert sign(1700000000, "POST", "/api/v1/bot/whoami/", "42", b'{"a":1}', token=TOKEN, nonce=NONCE) == VECTOR


def test_verify_window_and_tamper():
    args = ("POST", "/api/v1/bot/whoami/", "42", b'{"a":1}')
    ts = 1700000000
    assert verify(VECTOR, ts, *args, token=TOKEN, nonce=NONCE, now=ts + 299)
    assert not verify(VECTOR, ts, *args, token=TOKEN, nonce=NONCE, now=ts + 301)
    assert not verify(VECTOR, ts, "POST", "/api/v1/bot/whoami/", "43", b'{"a":1}', token=TOKEN, nonce=NONCE, now=ts)
    assert not verify(VECTOR, ts, "POST", "/api/v1/bot/whoami/", "42", b'{"a":2}', token=TOKEN, nonce=NONCE, now=ts)


def test_nonce_required_and_signed():
    ts = 1700000000
    args = ("POST", "/api/v1/bot/whoami/", "42", b'{"a":1}')
    assert not verify(VECTOR, ts, *args, token=TOKEN, now=ts)  # no nonce
    assert not verify(VECTOR, ts, *args, token=TOKEN, nonce="f" * 32, now=ts)
