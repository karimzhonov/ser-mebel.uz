"""Signed HTTP client for the backend's internal bot API (docs/BOT_CONTRACT.md).

Usage::

    from bot.backend.client import backend, ServiceRefusal

    data = await backend.request("GET", "finance/config/", actor=tg_id)
    op = await backend.request("POST", "finance/operations/", actor=tg_id, json={...})

`path` is relative to ``/api/v1/bot/`` (no leading slash). Pass ``actor`` (Telegram id)
for every call made on behalf of a user; it is covered by the signature and the backend
enforces all role rules. ``backend`` is a module-level singleton: tests monkeypatch
``backend.request`` (do not rebind the name).
"""

from __future__ import annotations

import asyncio
import json as jsonlib
import logging
import re
import uuid
from dataclasses import dataclass
from urllib.parse import quote, urlencode

import aiohttp
from yarl import URL

from config import BACKEND_URL

from .signing import HEADER_ACTOR, HEADER_SIG, HEADER_TS, signed_headers

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1/bot/"
TIMEOUT = aiohttp.ClientTimeout(total=20)
RAW_TIMEOUT = aiohttp.ClientTimeout(total=60)


class BackendError(Exception):
    """Base of all backend errors. `detail` is the backend's (Uzbek) message."""

    def __init__(self, detail: str = "", status: int = 0):
        super().__init__(detail)
        self.detail = detail
        self.status = status


class ServiceRefusal(BackendError):
    """400: a business rule said no. Show `❗ {detail}`."""


class Forbidden(BackendError):
    """403: the role may not do this (or a bad signature)."""


class NotFound(BackendError):
    """404."""


class Conflict(BackendError):
    """409: already done (answered request, marked handover, ...)."""


class BackendDown(BackendError):
    """Connection error, timeout or 5xx."""


@dataclass
class RawResponse:
    content: bytes
    content_type: str
    filename: str | None = None


_FILENAME = re.compile(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", re.I)


# Django signs get_full_path() = escape_uri_path(decoded path): this safe set, '%' quoted.
PATH_SAFE = "/:@&+$,-_.!~*'()"


def canonical_path(path: str) -> str:
    """The exact path string we send AND sign (what Django's request.get_full_path()
    reproduces). Callers pass RAW refs (Cyrillic, spaces, '@', '+', '%'): they are
    encoded here once, never by the call sites."""
    return quote(path, safe=PATH_SAFE)


def _detail(body: bytes) -> str:
    try:
        data = jsonlib.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return ""
    if isinstance(data, dict):
        d = data.get("detail")
        if d:
            return str(d)
        return "; ".join(f"{k}: {v}" for k, v in list(data.items())[:3])
    return str(data)


def _multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    out = bytearray()
    for name, value in (fields or {}).items():
        if value is None:
            continue
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += str(value).encode("utf-8") + b"\r\n"
    for name, spec in (files or {}).items():
        if isinstance(spec, (bytes, bytearray)):
            fname, content, ctype = name, bytes(spec), "application/octet-stream"
        else:
            fname, content, ctype = (tuple(spec) + ("application/octet-stream",))[:3]
        out += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
            f'filename="{fname}"\r\nContent-Type: {ctype}\r\n\r\n'
        ).encode()
        out += content + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


async def _forget_whoami(actor) -> None:
    """A write made for this person may change their roles: drop the cached whoami."""
    try:
        from bot.common.rds import get_redis

        await get_redis().delete(f"whoami:{actor}")
    except Exception:  # noqa: BLE001 - the cache is optional
        logger.warning("could not drop whoami cache for %s", actor)


class BackendClient:
    def __init__(self, base_url: str | None = None):
        self._base = (base_url or BACKEND_URL).rstrip("/")
        self._session: aiohttp.ClientSession | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get_session(self) -> aiohttp.ClientSession:
        loop = asyncio.get_running_loop()
        if self._session is None or self._session.closed or self._loop is not loop:
            self._session = aiohttp.ClientSession(timeout=TIMEOUT)
            self._loop = loop
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def request(
        self,
        method: str,
        path: str,
        *,
        actor=None,
        json=None,
        params: dict | None = None,
        files: dict | None = None,
        raw: bool = False,
    ):
        """One signed call. Returns parsed JSON (None for an empty body), or a
        `RawResponse` when raw=True. `files` is {field: (filename, bytes, content_type)};
        with files, `json` is sent as plain form fields (multipart)."""
        method = method.upper()
        full = canonical_path(API_PREFIX + path.lstrip("/"))
        if params:
            qs = urlencode({k: v for k, v in params.items() if v is not None})
            if qs:
                full += ("&" if "?" in full else "?") + qs
        headers: dict[str, str] = {}
        body = b""
        if files:
            body, headers["Content-Type"] = _multipart(json or {}, files)
        elif json is not None:
            body = jsonlib.dumps(json, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        headers.update(signed_headers(method, full, actor, body))
        url = URL(self._base + full, encoded=True)
        timeout = RAW_TIMEOUT if raw else TIMEOUT
        attempts = 2 if method == "GET" else 1
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                async with self._get_session().request(
                    method, url, data=body or None, headers=headers, timeout=timeout
                ) as resp:
                    content = await resp.read()
                    status = resp.status
                    ctype = resp.headers.get("Content-Type", "")
                    disp = resp.headers.get("Content-Disposition", "")
                break
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
                last = e
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.5)
        else:
            logger.error("backend %s %s unreachable: %s", method, path, last)
            raise BackendDown(str(last))

        if method != "GET" and actor is not None and path != "whoami/":
            await _forget_whoami(actor)
        if status >= 500:
            logger.error("backend %s %s answered %s", method, path, status)
            raise BackendDown(f"HTTP {status}", status)
        if status >= 400:
            detail = _detail(content)
            logger.info("backend %s %s -> %s %s", method, path, status, detail)
            cls = {400: ServiceRefusal, 403: Forbidden, 404: NotFound, 409: Conflict}.get(
                status, ServiceRefusal
            )
            raise cls(detail, status)
        if raw:
            m = _FILENAME.search(disp or "")
            return RawResponse(content, ctype.split(";")[0].strip(), m.group(1) if m else None)
        if status == 204 or not content:
            return None
        try:
            return jsonlib.loads(content.decode("utf-8"))
        except ValueError:
            raise BackendDown("bad JSON from backend", status)


backend = BackendClient()


def get_backend() -> BackendClient:
    return backend


__all__ = [
    "API_PREFIX",
    "BackendClient",
    "BackendDown",
    "BackendError",
    "Conflict",
    "Forbidden",
    "HEADER_ACTOR",
    "HEADER_SIG",
    "HEADER_TS",
    "NotFound",
    "RawResponse",
    "ServiceRefusal",
    "backend",
    "get_backend",
]
