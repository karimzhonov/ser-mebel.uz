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

    notify_price_task(price)

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


def save_calculation(
    *,
    price,
    object_type,
    name: str,
    count: float,
    items: list,
    calculation=None,
    room=None,
    note: str = "",
):
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
            raise ServiceError("Har bir tur uchun bitta mahsulot tanlanadi")
        by_type[type_id] = item

    if room is not None:
        if room.price_id != price.pk:
            raise ServiceError("Xona bu hisob-kitobga tegishli emas")
        allowed = set(room.room_type.object_types.values_list("pk", flat=True))
        if allowed and object_type.pk not in allowed:
            raise ServiceError(f"«{object_type.name}» «{room.room_type.name}» xonasiga mos emas")

    inv_types = {t.pk: t for t in InventoryType.objects.filter(obj=object_type)}
    unknown = set(by_type) - set(inv_types)
    if unknown:
        raise ServiceError("Mahsulot turi bu obyektga tegishli emas")

    with transaction.atomic():
        calc = calculation or Calculate(price=price, obj=object_type)
        calc.obj = object_type
        calc.name = name
        calc.count = count
        calc.room = room
        calc.note = (note or "").strip()
        calc.save()

        amount = 0.0
        for type_id, inv_type in inv_types.items():
            item = by_type.get(type_id)
            inventory_id = item.get("inventory") if item else None
            InventoryInCalculate.objects.filter(calculate=calc, inventory__type_id=type_id).delete()
            if not inventory_id:
                continue
            inventory = Inventory.objects.filter(pk=inventory_id, type_id=type_id).first()
            if inventory is None:
                raise ServiceError(f"«{inv_type.name}» uchun mahsulot topilmadi")
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


# --- Rooms (xonalar) --------------------------------------------------------------


def add_room(price, room_type, name: str = ""):
    """«Yotoqxona» added twice becomes «Yotoqxona 2» unless a name is given."""
    from django.db.models import Max

    from .models import Room

    name = (name or "").strip()
    if not name:
        same = Room.objects.filter(price=price, room_type=room_type).count()
        name = room_type.name if not same else f"{room_type.name} {same + 1}"
    last = Room.objects.filter(price=price).aggregate(m=Max("ordering"))["m"]
    return Room.objects.create(
        price=price, room_type=room_type, name=name, ordering=(last or 0) + 1
    )


def rename_room(room, name: str):
    from core.exceptions import ServiceError

    name = (name or "").strip()
    if not name:
        raise ServiceError("Xona nomini kiriting")
    room.name = name
    room.save(update_fields=["name"])
    return room


def reorder_rooms(price, ids: list[int]) -> None:
    from core.exceptions import ServiceError

    from .models import Room

    rooms = {r.pk: r for r in Room.objects.filter(price=price)}
    if set(ids) != set(rooms):
        raise ServiceError("Xonalar ro'yxati eskirgan — sahifani yangilang")
    with transaction.atomic():
        for i, pk in enumerate(ids, start=1):
            if rooms[pk].ordering != i:
                rooms[pk].ordering = i
                rooms[pk].save(update_fields=["ordering"])


def delete_room(room) -> None:
    """The room's furniture goes with it; the total is recomputed."""
    price = room.price
    with transaction.atomic():
        room.delete()  # CASCADE: its Calculate rows and image links
        recompute_price_total(price)


def price_folder(price):
    """The calculation's filer folder (made for a calculation without a metering too)."""
    if price.folder_id:
        return price.folder
    folder = Folder.objects.create(name=f"Расчёт цены #{price.pk}")
    price.folder = folder
    price.save(update_fields=["folder"])
    return folder


def add_room_images(user, room, uploads) -> list:
    """`uploads` are already checked to be images (the API normalises their names).
    Stored as filer images in «<price folder>/<room name>»."""
    from django.db.models import Max
    from filer.models import Image

    from .models import RoomImage

    with transaction.atomic():
        folder, _ = Folder.objects.get_or_create(
            name=room.name[:255], parent=price_folder(room.price), defaults={"owner": user}
        )
        last = room.images.aggregate(m=Max("ordering"))["m"] or 0
        out = []
        for i, upload in enumerate(uploads, start=1):
            img = Image(folder=folder, owner=user, original_filename=upload.name, file=upload)
            img.save()
            out.append(RoomImage.objects.create(room=room, file=img, ordering=last + i))
    return out


def delete_room_image(image) -> None:
    """Drops the picture from the offer; the file stays in the folder."""
    image.delete()


# --- The commercial offer: one structure for the page, the Excel and the PDF ---------


def offer_data(price) -> dict:
    """Rooms → furniture → «label: material» lines, with the per-item and per-room sums
    (USD). Per-line prices are deliberately left out — the client sees item prices only.
    Calculations made before rooms existed are grouped under «Boshqa»."""
    from datetime import date

    from django.db.models import Prefetch

    from .models import Calculate, InventoryInCalculate, Room

    lines_qs = InventoryInCalculate.objects.select_related("inventory__type").order_by(
        "inventory__type__ordering", "inventory__type_id", "id"
    )
    calcs_qs = (
        Calculate.objects.select_related("obj")
        .prefetch_related(Prefetch("inventoryincalculate_set", queryset=lines_qs))
        .order_by("id")
    )
    rooms = list(
        Room.objects.filter(price=price)
        .select_related("room_type")
        .prefetch_related(Prefetch("calculations", queryset=calcs_qs), "images__file")
    )

    def item(c):
        unit = "м²" if c.obj.count_name == "kv" else "п.м."
        params = []
        for ic in c.inventoryincalculate_set.all():
            t = ic.inventory.type
            value = ic.inventory.name
            if t.type == t.TYPE_COUNT and ic.count and ic.count != 1:
                value = f"{value} × {_num(ic.count)}"
            params.append({"label": t.name, "value": value})
        return {
            "id": c.id,
            "name": c.name,
            "object": c.obj.name,
            "count": c.count,
            "count_text": f"{_num(c.count)} {unit}" if c.count else "",
            "params": params,
            "note": c.note,
            "amount": round(float(c.amount.amount), 2) if c.amount is not None else 0.0,
        }

    out_rooms = []
    for r in rooms:
        items = [item(c) for c in r.calculations.all()]
        out_rooms.append(
            {
                "id": r.id,
                "name": r.name,
                "room_type": r.room_type.name,
                "icon": r.room_type.icon,
                "images": [im.file for im in r.images.all()],
                "items": items,
                "total": round(sum(i["amount"] for i in items), 2),
            }
        )
    loose = [item(c) for c in calcs_qs.filter(price=price, room__isnull=True)]
    if loose:
        out_rooms.append(
            {
                "id": None,
                "name": "Boshqa",
                "room_type": "",
                "icon": "📦",
                "images": [],
                "items": loose,
                "total": round(sum(i["amount"] for i in loose), 2),
            }
        )
    client = price.metering.client if price.metering_id else None
    estimator = price.user
    return {
        "client": price.client_title or (str(client.fio) if client else (price.desc or "")),
        "estimator": (estimator.name or str(estimator.phone)) if estimator else "",
        "date": date.today(),  # USE_TZ is off: server local time
        "variant": price.variant,
        "rooms": out_rooms,
        "total": round(sum(r["total"] for r in out_rooms), 2),
        "currency": "USD",
    }


def _num(v) -> str:
    """3.15 → «3,15», 4.0 → «4» (the way the offer writes sizes)."""
    v = float(v or 0)
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


def mark_price_done(price):
    from core.exceptions import ServiceError

    if price.done:
        raise ServiceError("Narx allaqachon hisoblangan")
    price.done = True
    price.save()
    return price


def notify_price_task(price) -> None:
    """Price task: only the assigned person when there is one, otherwise (old admin flow)
    the call-centre staff. Sent after the transaction commits."""
    # robust: a failing send is logged and never turns a saved change into a 500.
    transaction.on_commit(lambda: _send_price_task(price), robust=True)


def _send_price_task(price) -> None:
    import logging

    from oauth.services import notify_user

    text = f"{price.metering.client} mijozga narx chiqarish kerak"
    context = {"buyurtma_raqami": price.metering_id}
    if price.user_id:
        notify_user(
            price.user,
            url=f"/prices/{price.pk}",
            telegram_text=text,
            sms_template=SMS_PRICE_NEEDED,
            sms_context=context,
        )
        return
    try:
        User.send_messages(
            CALL_CENTER_PERMISSION,
            "admin:price_price_change",
            {"object_id": price.pk},
            text=text,
            sms_template=SMS_PRICE_NEEDED,
            sms_context=context,
        )
    except Exception:
        logging.getLogger(__name__).exception("Price task broadcast failed (%s)", price.pk)
