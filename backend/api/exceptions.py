from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from core.exceptions import ServiceError


def exception_handler(exc, context):
    """DRF's handler plus: a ServiceError (business rule said no) becomes a 400 whose
    `detail` is the message the service wrote for staff."""
    if isinstance(exc, ServiceError):
        return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)
    return drf_exception_handler(exc, context)
