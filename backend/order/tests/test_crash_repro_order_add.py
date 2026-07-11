"""Independent repro of the reported production crash:

    KeyError at /admin/order/order/add/
    'order_number'
    GET /admin/order/order/add/?client=%2B998909868887&address=...&address_link=...
        &reception_date=08.07.2026&metering=123&price=

Written independently of django-dev's self-report to verify the fix actually
resolves the crash end-to-end through the real admin add view.
"""

import datetime

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_order_add_view_with_prefill_querystring_does_not_500(logged_in_admin_client, db_client):
    from metering.design.models import Design
    from metering.models import Metering

    metering = Metering.objects.create(client=db_client, date_time=datetime.datetime.now())
    Design.objects.create(metering=metering)

    url = reverse("admin:order_order_add")
    query = {
        "client": "+998909868887",
        "address": "ЭШОНГУЗАР",
        "address_link": (
            "https://www.google.com/maps/place/41%C2%B014'53.9%22N+69%C2%B008'27.1%22E/"
            "@41.248291,69.140872,16z"
        ),
        "reception_date": "08.07.2026",
        "metering": str(metering.pk),
        "price": "",
    }

    response = logged_in_admin_client.get(url, query)

    assert response.status_code == 200, getattr(response, "content", b"")[:2000]
