from urllib.parse import urlparse, parse_qs
from django.http.request import HttpRequest
from .constants import DashboardFilterChoices

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
        },
        {
            "title": "Бухгалтерия",
            "link": '/admin/?tab=accounting',
            "html_file": 'accounting/dashboard.html',
            "icon": "finance_mode",
            "permission": "accounting.view_expense",
        },
        {
            "title": "Очеред заказов",
            "link": '/admin/?tab=order_wait_list',
            "html_file": 'order/order_wait_list.html',
            "icon": "box",
            "permission": "order.wait_list_order",
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
            "title": "Все",
            "slug": '',
        }
    ]

    for choice in DashboardFilterChoices.choices:
        filters.append({
            "title": choice[1],
            "slug": choice[0],
        })

    for fil in filters:
        if fil['slug'] == filter:
            fil['active'] = True
            return filters
    return filters


def dashboard_callback(request: HttpRequest, context):
    request.GET._mutable = True
    tab = ''.join(request.GET.pop('tab', []))
    date = ''.join(request.GET.get('date', []))
    nav, navigation = get_navigation(tab)
    filters = get_filters(date)
    context.update(
        tab=tab,
        navigation=filter(lambda n: True if not n["permission"] else request.user.has_perm(n['permission']), navigation),
        current_navigation=nav,
        filters=filters
    )
    return context

