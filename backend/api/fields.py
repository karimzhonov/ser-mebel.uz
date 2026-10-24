from decimal import Decimal, InvalidOperation

from djmoney import settings as dj_settings
from djmoney.money import Money
from rest_framework import serializers


class MoneyField(serializers.Field):
    """Money <-> {"amount": 1200.0, "currency": "USD"}.

    Input may also be a bare number (DEFAULT_CURRENCY is assumed).
    """

    default_error_messages = {
        "invalid": "Summa noto'g'ri.",
        "currency": "Valyuta noto'g'ri.",
    }

    def to_representation(self, value):
        if value is None or value.amount is None:
            return None
        return {"amount": float(value.amount), "currency": str(value.currency)}

    def to_internal_value(self, data):
        if isinstance(data, dict):
            amount = data.get("amount")
            currency = data.get("currency") or dj_settings.DEFAULT_CURRENCY
        else:
            amount, currency = data, dj_settings.DEFAULT_CURRENCY
        if currency not in [code for code, _ in dj_settings.CURRENCY_CHOICES]:
            self.fail("currency")
        try:
            amount = Decimal(str(amount)).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError):
            self.fail("invalid")
        # MoneyField(max_digits=12, decimal_places=2) everywhere: |amount| < 10**10.
        # Also rejects NaN/Infinity, which Postgres would store and poison every Sum.
        if not amount.is_finite() or abs(amount) >= Decimal(10) ** 10:
            self.fail("invalid")
        return Money(amount, currency)
