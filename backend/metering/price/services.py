from django.db import transaction
from filer.models.foldermodels import Folder

from core.notifications import SMS_PRICE_NEEDED
from oauth.models import CALL_CENTER_PERMISSION, User


def notify_and_create_price_folder(price) -> None:
    """Notify call-center staff that a price needs to be calculated and create
    the Filer folder for this Price nested under its Metering's folder.

    No-ops when the Price has no linked Metering (metering=None is a valid
    state — see PriceAdmin, which allows creating a Price without a metering).
    """
    if price.metering is None:
        return

    User.send_messages(
        CALL_CENTER_PERMISSION,
        "admin:price_price_change",
        {"object_id": price.pk},
        text=f"{price.metering.client} mijozga narx chiqarish kerak",
        sms_template=SMS_PRICE_NEEDED,
        sms_context={"buyurtma_raqami": price.metering_id},
    )

    created_history = price.history.order_by("history_date").first()
    created_user = created_history.history_user if created_history else None

    with transaction.atomic():
        price_folder, _ = Folder.objects.get_or_create(
            name="Расчёт цены", parent=price.metering.folder, defaults={"owner": created_user}
        )
        price.folder = price_folder
        price.save(update_fields=["folder"])


# --- Write services (used by the REST API; mirror CalculateForm.save / PriceAdmin) ---


def recompute_price_total(price) -> None:
    """Mirrors PriceAdmin.save_related: Price.price = sum of its calculations (USD),
    pushed down to the order made from the same metering."""
    from djmoney.money import Money

    from order.models import Order

    from .models import Calculate

    amount = 0
    for calc in Calculate.objects.filter(price=price):
        if calc.amount is not None:
            amount += calc.amount.amount
    price.price = Money(amount, currency="USD")
    price.save()
    if price.metering_id:
        Order.objects.filter(metering_id=price.metering_id).update(
            price=Money(amount, currency="USD")
        )


def save_calculation(*, price, object_type, name: str, count: float, items: list, calculation=None):
    """Create or update one Calculate row and its inventory lines.

    `items` is a list of {"inventory_type": id, "inventory": id | None, "count": float | None}
    — at most one inventory per InventoryType, same as the admin form. For a TYPE_KV
    inventory type the line count is the calculation's own count (м² / пог. м); for
    TYPE_COUNT it is the item's count.

    Difference from the admin form, on purpose: an inventory type left empty removes
    its old line instead of silently keeping it (the admin kept a stale line that was
    still printed in the Excel but no longer counted in the total).
    """
    from djmoney.money import Money

    from core.exceptions import ServiceError

    from .models import Calculate, Inventory, InventoryInCalculate, InventoryType

    by_type = {}
    for item in items or []:
        type_id = int(item["inventory_type"])
        if type_id in by_type:
            raise ServiceError("Ҳар бир тур учун битта товар танланади")
        by_type[type_id] = item

    inv_types = {t.pk: t for t in InventoryType.objects.filter(obj=object_type)}
    unknown = set(by_type) - set(inv_types)
    if unknown:
        raise ServiceError("Товар тури бу объектга тегишли эмас")

    with transaction.atomic():
        calc = calculation or Calculate(price=price, obj=object_type)
        calc.name = name
        calc.count = count
        calc.save()

        amount = 0.0
        for type_id, inv_type in inv_types.items():
            item = by_type.get(type_id)
            inventory_id = item.get("inventory") if item else None
            InventoryInCalculate.objects.filter(
                calculate=calc, inventory__type_id=type_id
            ).delete()
            if not inventory_id:
                continue
            inventory = Inventory.objects.filter(pk=inventory_id, type_id=type_id).first()
            if inventory is None:
                raise ServiceError(f"«{inv_type.name}» учун товар топилмади")
            if inv_type.type == InventoryType.TYPE_KV:
                line_count = float(count or 0)
            else:
                line_count = float(item.get("count") or 0)
            unit = inventory.price
            line_amount = line_count * float(unit.amount) if unit is not None else 0.0
            InventoryInCalculate.objects.create(
                inventory=inventory,
                calculate=calc,
                count=line_count,
                price=Money(amount=line_amount, currency=unit.currency if unit else "USD"),
            )
            amount += line_amount

        calc.amount = Money(amount, currency="USD")
        calc.save()
        recompute_price_total(price)
    return calc


def delete_calculation(calculation) -> None:
    price = calculation.price
    with transaction.atomic():
        calculation.delete()
        recompute_price_total(price)


def mark_price_done(price):
    from core.exceptions import ServiceError

    if price.done:
        raise ServiceError("Нарх аллақачон чиқарилган")
    price.done = True
    price.save()
    return price
