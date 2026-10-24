import re

from rest_framework import status
from rest_framework.exceptions import ErrorDetail
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from core.exceptions import ServiceError

from .i18n import DEFAULT_ERROR, ERROR_CODE

_CYRILLIC = re.compile(r"[А-Яа-яЁёЎўҚқҒғҲҳ]")


def _uzbek(detail):
    """Library messages come in Russian (LANGUAGE_CODE="ru", kept for the admin);
    swap any Cyrillic message for its Uzbek text by error code. Our own messages
    are already Uzbek (Latin) and pass through untouched."""
    if isinstance(detail, dict):
        return {key: _uzbek(value) for key, value in detail.items()}
    if isinstance(detail, list):
        return [_uzbek(item) for item in detail]
    if isinstance(detail, str) and _CYRILLIC.search(detail):
        code = getattr(detail, "code", None)
        return ErrorDetail(ERROR_CODE.get(code, DEFAULT_ERROR), code=code)
    return detail


def exception_handler(exc, context):
    """DRF's handler plus: a ServiceError (business rule said no) becomes a 400 whose
    `detail` is the message the service wrote for staff; every message is Uzbek."""
    if isinstance(exc, ServiceError):
        return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)
    response = drf_exception_handler(exc, context)
    if response is None:
        return response
    # Http404 / Django's PermissionDenied reach here without `.detail` on `exc` (DRF
    # converts them internally), so translate what DRF put in the response.
    if response.status_code == status.HTTP_404_NOT_FOUND:
        response.data = {"detail": ERROR_CODE["not_found"]}  # e.g. "No X matches the given query."
        return response
    data = _uzbek(response.data)
    if isinstance(data, (str, list)):
        data = {"detail": data}
    response.data = data
    return response
