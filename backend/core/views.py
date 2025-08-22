from urllib.parse import urlparse, parse_qs
from django.http.request import HttpRequest


def get_navigation(tab):
    navigation = [
        {
            "title": "Дашбоард",
            "link": '/admin/',
            "html_file": 'dashboard.html',
            "icon": "home",
            "permission": None
        },
        {
            "title": "Клиенты",
            "link": '/admin/?tab=client',
            "html_file": 'client/dashboard.html',
            "icon": "people",
            "permission": "client.view_client",
        },
        {
            "title": "Call-center",
            "link": '/admin/?tab=call_center',
            "html_file": 'call_center/dashboard.html',
            "icon": "phone",
            "permission": "call_center.view_call_center",
        },
        {
            "title": "Замер",
            "link": '/admin/?tab=metering',
            "html_file": 'metering/dashboard.html',
            "icon": "design_services",
            "permission": "metering.view_metering",
        },
        {
            "title": "Заказ",
            "link": '/admin/?tab=order',
            "html_file": 'order/dashboard.html',
            "icon": "box",
            "permission": "order.view_order",
        }
    ]
    
    for nav in navigation:
        if ''.join(parse_qs(urlparse(nav['link']).query).get('tab', [])) == tab:
            nav['active'] = True
            return nav, navigation
    return None, navigation


def get_filters(filter):
    filters = [
        {
            "title": "All",
            "slug": '',
        },
        {
            "title": "Last year",
            "slug": 'year',
        },
        {
            "title": "Last month",
            "slug": 'month',
        },
        {
            "title": "Last week",
            "slug": 'week',
        },
    ]

    for fil in filters:
        if fil['slug'] == filter:
            fil['active'] = True
            return filters
    return filters


def dashboard_callback(request: HttpRequest, context):
    request.GET._mutable = True
    tab = ''.join(request.GET.pop('tab', []))
    date = ''.join(request.GET.pop('date', []))
    nav, navigation = get_navigation(tab)
    filters = get_filters(date)
    context.update(
        tab=tab,
        navigation=filter(lambda n: True if not n["permission"] else request.user.has_perm(n['permission']), navigation),
        current_navigation=nav,
        filters=filters
    )
    return context

