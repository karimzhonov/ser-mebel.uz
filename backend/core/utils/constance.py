from djmoney.money import Money
from constance.backends.database import DatabaseBackend as _DatabaseBackend
from constance.codecs import register_type


def money_encoder(obj):
    return {
        "__money__": True,
        "amount": int(obj.amount),
        "currency": obj.currency.code,
    }


def money_decoder(dct):
    if "__money__" in dct:
        return Money(int(dct["amount"]), dct["currency"])
    return dct


register_type(Money, 'Money', money_encoder, money_decoder)

class DatabaseBackend(_DatabaseBackend):
    pass
