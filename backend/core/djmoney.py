from django.db.models import Manager
from django.http.request import HttpRequest
from django.db.models.query import QuerySet
from django.db.models import F, ExpressionWrapper, DecimalField, FloatField, Value, Case, When
from django.utils.deprecation import MiddlewareMixin
from djmoney.contrib.exchange.backends.base import SimpleExchangeBackend
from djmoney.settings import DEFAULT_CURRENCY, BASE_CURRENCY


class CBUBackend(SimpleExchangeBackend):
    name = "CBU Backend"
    url = "https://cbu.uz/ru/arkhiv-kursov-valyut/json/"
    currency_url = "https://cbu.uz/ru/arkhiv-kursov-valyut/json/{currency}/"

    def get_url(self, **params):
        if params.get('currency'):
            self.url = self.currency_url.format(currency=params.get('currency'))
        return super().get_url(**params)

    def get_rates(self, **params) -> dict:
        response = self.get_response(**params)
        currencies = self.parse_json(response)
        return {
            currency['Ccy']: currency['Rate'] for currency in currencies
        }


def get_rate(currency):
    backend = CBUBackend()
    rates = backend.get_rates(currency='USD')
    rate = float(rates.get('USD', 1))
    return (1 / rate) if currency == 'USD' else rate


class ConvertedCostManager(Manager):
    request: HttpRequest

    def __init__(self, fields: list[str]) -> None:
        super().__init__()
        self.fields = fields

    def get_queryset(self) -> QuerySet:
        currency = ''.join(self.request.GET.get('currency', [DEFAULT_CURRENCY]))
        try:
            rate = get_rate(currency)            
        except Exception as _exp:
            print(_exp)
            rate = get_rate(DEFAULT_CURRENCY)
            currency = DEFAULT_CURRENCY
        print(rate)
        annotate_dict = {}

        for field in self.fields:
            annotate_dict[f'converted_{field}'] = ExpressionWrapper(
                Case(
                    When(cost_currency=currency, then=F('cost')),
                    default=(F("cost") * rate) if rate else F('cost'),
                    output_field=FloatField()
                ),
                output_field=DecimalField()
            )
            annotate_dict[f'converted_{field}_currency'] = F(currency.format(field=field)) if not rate else Value(currency)
        
        return super().get_queryset().annotate(**annotate_dict)


class ConvertedCostMiddleware(MiddlewareMixin):

    def process_request(self, request):
        ConvertedCostManager.request = request

    def process_response(self, request, response):
        ConvertedCostManager.request = None
        return response
    