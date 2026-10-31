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


# --- Lock: the calculation can change until the order goes to detailing -------------

EDITABLE_ORDER_STATUSES = ("waiting", "created")
LOCKED_MESSAGE = "Buyurtma detalirovkaga o'tgan — hisob-kitobni endi o'zgartirib bo'lmaydi"


def price_locked(price) -> bool:
    """True once the order made from this calculation's metering has reached
    detailing (or any later stage)."""
    from order.models import Order

    if not price.metering_id:
        return False
    status = (
        Order.objects.filter(metering_id=price.metering_id).values_list("status", flat=True).first()
    )
    return status is not None and status not in EDITABLE_ORDER_STATUSES


def assert_editable(price) -> None:
    from core.exceptions import ServiceError

    if price_locked(price):
        raise ServiceError(LOCKED_MESSAGE)


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
    color: str = "",
    manual_amount=None,
    accessories: list | None = None,
    unit: str = "",
    height: int | None = None,
    width: int | None = None,
    depth: int | None = None,
):
    """Create or update one Calculate row, its inventory lines and accessories.

    `accessories`: [{"id"?, "inventory"?, "name", "count", "price", "image"?}] — the
    whole list (rows left out are deleted). `price` is the unit price in USD; picked
    from the catalog it defaults to the catalog price. `image` is a filer image id
    uploaded with add_accessory_image(). amount = manual_amount when given, else the
    catalog lines + accessories (auto_amount).

    `items` is a list of {"inventory_type": id, "inventory": id | None, "count": float | None}
    — at most one inventory per InventoryType, same as the admin form. For a TYPE_KV
    inventory type the line count is the calculation's own count (м² / пог. м); for
    TYPE_COUNT it is the item's count.

    Difference from the admin form, on purpose: an inventory type left empty removes
    its old line instead of silently keeping it (the admin kept a stale line that was
    still printed in the Excel but no longer counted in the total).
    """
    from django.db.models import Q
    from djmoney.money import Money

    from core.exceptions import ServiceError

    from .models import Calculate, Inventory, InventoryInCalculate, InventoryType

    assert_editable(price)
    if unit not in ("", "kv", "pog"):
        raise ServiceError("O'lchov birligi: kv yoki pog")
    count = size_count(unit or object_type.count_name, height, width, count)
    by_type = {}
    for item in items or []:
        type_id = int(item["inventory_type"])
        if type_id in by_type:
            raise ServiceError("Har bir tur uchun bitta mahsulot tanlanadi")
        by_type[type_id] = item

    if object_type.archived and (calculation is None or calculation.obj_id != object_type.pk):
        raise ServiceError(f"«{object_type.name}» arxivda — boshqa mebel tanlang")

    if room is not None:
        if room.price_id != price.pk:
            raise ServiceError("Xona bu hisob-kitobga tegishli emas")
        allowed = set(room.room_type.object_types.values_list("pk", flat=True))
        if allowed and object_type.pk not in allowed:
            raise ServiceError(f"«{object_type.name}» «{room.room_type.name}» xonasiga mos emas")

    # + the cards this piece already uses: a card moved to another object since then
    # stays editable here (and its line is not silently dropped from the total)
    used = (
        InventoryInCalculate.objects.filter(calculate=calculation).values("inventory__type_id")
        if calculation is not None
        else InventoryInCalculate.objects.none().values("inventory__type_id")
    )
    inv_types = {t.pk: t for t in InventoryType.objects.filter(Q(obj=object_type) | Q(pk__in=used))}
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
        calc.color = (color or "").strip()
        calc.unit = unit
        calc.height, calc.width, calc.depth = height or None, width or None, depth or None
        calc.manual_amount = manual_amount
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

        amount += _save_accessories(price, calc, accessories or [])
        calc.auto_amount = round(amount, 2)
        final = float(manual_amount) if manual_amount is not None else amount
        calc.amount = Money(final, currency="USD")
        calc.save()
        recompute_price_total(price)
    return calc


def size_count(unit: str, height, width, typed):
    """kv. m = height × width, pog. m = width (sizes in mm). Without the sizes it needs,
    the typed figure stays."""
    if width and unit == "pog":
        return round(width / 1000, 3)
    if width and height and unit == "kv":
        return round(height * width / 1_000_000, 3)
    return typed


def measure_text(item: dict) -> str:
    """«3,15 м² · 2400 × 1800 × 600 мм» — what the offer prints under a furniture name."""
    return " · ".join(t for t in (item.get("count_text"), item.get("size_text")) if t)


def client_measure_text(item: dict) -> str:
    """What the client's PDF prints under a furniture name: running metres stay in
    p.m., decor stays in m², other furniture shows its size instead of m² (falling back
    to m² when no size was entered). Pricing is unaffected."""
    if item.get("unit") == "kv" and not item.get("show_area") and item.get("size_text"):
        return item["size_text"]
    return measure_text(item)


def size_text(height, width, depth) -> str:
    """2400 × 1800 × 600 мм (only the sizes that were given)."""
    parts = [str(v) for v in (height, width, depth) if v]
    return f"{' × '.join(parts)} мм" if parts else ""


def _save_accessories(price, calc, rows: list) -> float:
    from decimal import Decimal

    from filer.models import Image

    from core.exceptions import ServiceError

    from .models import CalcAccessory, Inventory

    existing = {a.pk: a for a in calc.accessories.all()}
    keep, total = set(), 0.0
    for i, row in enumerate(rows, start=1):
        acc = existing.get(row.get("id")) or CalcAccessory(calculate=calc)
        inv = None
        if row.get("inventory"):
            inv = Inventory.objects.select_related("type").filter(pk=row["inventory"]).first()
            if inv is None:
                raise ServiceError("Katalogdagi mahsulot topilmadi")
            if inv.type.obj_id != calc.obj_id and acc.inventory_id != inv.pk:
                raise ServiceError(
                    f"«{inv.name}» bu mebelga tegishli emas — uni xonaga alohida mebel qilib qo'shing"
                )
        name = (row.get("name") or (inv.name if inv else "")).strip()
        if not name:
            raise ServiceError("Aksessuar nomini kiriting")
        unit = row.get("price")
        if unit in (None, "") and inv is not None and inv.price is not None:
            unit = inv.price.amount
        image = None
        if row.get("image"):
            image = Image.objects.filter(pk=row["image"]).first()
            if image is None or not _in_price_folder(price, image):
                raise ServiceError("Aksessuar rasmi topilmadi")
        acc.inventory = inv
        acc.name = name[:255]
        acc.count = float(row.get("count") or 1)
        acc.unit_price = Decimal(str(unit or 0))
        acc.image = image
        acc.ordering = i
        acc.save()
        keep.add(acc.pk)
        total += acc.amount
    calc.accessories.exclude(pk__in=keep).delete()
    return total


def _in_price_folder(price, file) -> bool:
    root = price.folder_id
    folder = file.folder
    while folder is not None:
        if folder.pk == root:
            return True
        folder = folder.parent
    return False


def add_accessory_image(user, price, upload):
    """An accessory picture goes to «<price folder>/Aksessuarlar»; the calculation
    editor then sends its id with the accessory row."""
    from filer.models import Image

    assert_editable(price)
    folder, _ = Folder.objects.get_or_create(
        name="Aksessuarlar", parent=price_folder(price), defaults={"owner": user}
    )
    img = Image(folder=folder, owner=user, original_filename=upload.name, file=upload)
    img.save()
    return img


def delete_calculation(calculation) -> None:
    price = calculation.price
    assert_editable(price)
    with transaction.atomic():
        calculation.delete()
        recompute_price_total(price)


# --- Catalog («Mahsulotlar»): object types and their cards -------------------------


def move_inventory_type(inv_type, obj) -> None:
    """Move a card (mahsulot turi) with all its products to another object. Old
    calculations keep their lines: they point at the products, not at the object."""
    from core.exceptions import ServiceError

    if obj.archived:
        raise ServiceError(f"«{obj.name}» arxivda")
    if inv_type.obj_id == obj.pk:
        raise ServiceError(f"«{inv_type.name}» allaqachon «{obj.name}» ichida")
    inv_type.obj = obj
    inv_type.save(update_fields=["obj"])


def split_inventory_type(inv_type):
    """Turn a card into its own object («Komod» card of «Spalnya» → «Komod» object):
    the card moves into it with its products; the new object gets the old one's unit
    and rooms. An object with that name already there is reused."""
    from core.exceptions import ServiceError

    from .models import ObjectType, RoomType

    old = inv_type.obj
    name = inv_type.name.strip()
    with transaction.atomic():
        obj = ObjectType.objects.filter(name__iexact=name).first()
        if obj is None:
            obj = ObjectType.objects.create(
                name=name,
                count_name=old.count_name if old else "kv",
                show_area=old.show_area if old else False,
            )
        elif obj.pk == inv_type.obj_id:
            raise ServiceError(f"«{name}» allaqachon alohida obyekt")
        elif obj.archived:
            obj.archived = False
            obj.save(update_fields=["archived"])
        if old is not None:
            for rt in RoomType.objects.filter(object_types=old):
                rt.object_types.add(obj)
        inv_type.obj = obj
        inv_type.save(update_fields=["obj"])
    return obj


def retire_object_type(obj) -> str:
    """Delete an object type, or archive it when old calculations use it.
    Refused while it still has cards — move or delete them first."""
    from core.exceptions import ServiceError

    from .models import Calculate, InventoryType

    n = InventoryType.objects.filter(obj=obj).count()
    if n:
        raise ServiceError(
            f"«{obj.name}» ichida {n} ta mahsulot turi bor — avval ularni ko'chiring yoki o'chiring"
        )
    if Calculate.objects.filter(obj=obj).exists():
        obj.archived = True
        obj.save(update_fields=["archived"])
        return "archived"
    obj.delete()
    return "deleted"


# --- Rooms (xonalar) --------------------------------------------------------------


def add_room(price, room_type, name: str = ""):
    """«Yotoqxona» added twice becomes «Yotoqxona 2» unless a name is given."""
    from django.db.models import Max

    from .models import Room

    assert_editable(price)
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

    assert_editable(room.price)
    name = (name or "").strip()
    if not name:
        raise ServiceError("Xona nomini kiriting")
    room.name = name
    room.save(update_fields=["name"])
    return room


def reorder_rooms(price, ids: list[int]) -> None:
    from core.exceptions import ServiceError

    from .models import Room

    assert_editable(price)
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
    assert_editable(price)
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


def add_room_images(user, room, uploads, calculate=None) -> list:
    """`uploads` are already checked to be images (the API normalises their names).
    Stored as filer images in «<price folder>/<room name>»."""
    from django.db.models import Max
    from filer.models import Image

    from .models import RoomImage

    assert_editable(room.price)
    with transaction.atomic():
        folder, _ = Folder.objects.get_or_create(
            name=room.name[:255], parent=price_folder(room.price), defaults={"owner": user}
        )
        last = room.images.aggregate(m=Max("ordering"))["m"] or 0
        out = []
        for i, upload in enumerate(uploads, start=1):
            img = Image(folder=folder, owner=user, original_filename=upload.name, file=upload)
            img.save()
            out.append(
                RoomImage.objects.create(
                    room=room, file=img, ordering=last + i, calculate=calculate
                )
            )
    return out


def set_image_furniture(image, calculate) -> None:
    """Attach a room picture to one of the room's furniture (None = the whole room)."""
    from core.exceptions import ServiceError

    assert_editable(image.room.price)
    if calculate is not None and calculate.room_id != image.room_id:
        raise ServiceError("Bu mebel shu xonada emas")
    image.calculate = calculate
    image.save(update_fields=["calculate"])


def delete_room_image(image) -> None:
    """Drops the picture from the offer; the file stays in the folder."""
    assert_editable(image.room.price)
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
        .prefetch_related(
            Prefetch("inventoryincalculate_set", queryset=lines_qs),
            "accessories__image",
            "accessories__inventory__type",
        )
        .order_by("id")
    )
    rooms = list(
        Room.objects.filter(price=price)
        .select_related("room_type")
        .prefetch_related(
            Prefetch("calculations", queryset=calcs_qs.prefetch_related("images__file")),
            "images__file",
        )
    )

    def item(c):
        unit = "м²" if (c.unit or c.obj.count_name) == "kv" else "п.м."
        params = []
        for ic in c.inventoryincalculate_set.all():
            t = ic.inventory.type
            value = ic.inventory.name
            if t.type == t.TYPE_COUNT and ic.count and ic.count != 1:
                value = f"{value} × {_num(ic.count)}"
            params.append({"label": t.name, "value": value})
        accessories = [
            {
                # «Musor yashik» — the catalog type says what the item is
                "type": a.inventory.type.name if a.inventory_id else "",
                "name": a.name,
                "count": a.count,
                "count_text": _num(a.count),
                "amount": a.amount,
                "image": a.image,
            }
            for a in c.accessories.all()
        ]
        return {
            "id": c.id,
            "name": c.name,
            "object": c.obj.name,
            "count": c.count,
            "count_text": f"{_num(c.count)} {unit}" if c.count else "",
            "size_text": size_text(c.height, c.width, c.depth),
            "unit": c.unit or c.obj.count_name,
            "show_area": c.obj.show_area,
            "params": params,
            "color": c.color,
            "accessories": accessories,
            "images": [im.file for im in c.images.all()],
            "note": c.note,
            "auto_amount": float(c.auto_amount) if c.auto_amount is not None else None,
            "manual": c.manual_amount is not None,
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
                # the whole room; furniture pictures travel with their item
                "images": [im.file for im in r.images.all() if im.calculate_id is None],
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


def offer_lines(item: dict) -> list[dict]:
    """Every «label: value» line of one furniture item as the offer prints it: the
    catalog parameters, then colour / accessories / extra — only when filled in."""
    lines = list(item["params"])
    if item.get("color"):
        lines.append({"label": "Ранги", "value": item["color"]})
    for a in item.get("accessories") or []:
        value = a["name"] + (f" × {a['count_text']}" if a["count"] and a["count"] != 1 else "")
        lines.append({"label": a.get("type") or "Аксессуар", "value": value})
    if item.get("note"):
        lines.append({"label": "Қўшимча", "value": item["note"]})
    return lines


# --- Versions: what was given to the client, kept as it was ------------------------


def offer_snapshot(price) -> dict:
    """offer_data() made JSON-safe (dates as ISO, pictures as filer ids)."""
    data = offer_data(price)
    data["date"] = data["date"].isoformat()
    for r in data["rooms"]:
        r["images"] = [f.pk for f in r["images"]]
        for it in r["items"]:
            it["images"] = [f.pk for f in it["images"]]
            for a in it["accessories"]:
                a["image"] = a["image"].pk if a["image"] else None
    return data


def _comparable(data: dict) -> dict:
    return {k: v for k, v in data.items() if k != "date"}


def save_version(user, price, label: str = ""):
    """Freezes the current offer as the next version — unless nothing changed since
    the last one (then that one is returned)."""
    from decimal import Decimal

    from django.db.models import Max

    from .models import PriceVersion

    data = offer_snapshot(price)
    with transaction.atomic():
        last = (
            PriceVersion.objects.select_for_update().filter(price=price).order_by("-number").first()
        )
        if last is not None and _comparable(last.data) == _comparable(data) and not label:
            return last
        number = (PriceVersion.objects.filter(price=price).aggregate(m=Max("number"))["m"] or 0) + 1
        if not label:
            label = "Taxminiy narx" if number == 1 else f"{number}-taklif"
        return PriceVersion.objects.create(
            price=price,
            number=number,
            label=label[:255],
            total=Decimal(str(data["total"])),
            data=data,
            created_by=user if getattr(user, "pk", None) else None,
        )


def version_offer_data(version) -> dict:
    """A saved version back in offer_data() shape, for the PDF (pictures that were
    deleted since are skipped)."""
    import copy
    from datetime import date

    from filer.models import Image

    data = copy.deepcopy(version.data)
    ids = {i for r in data["rooms"] for i in r["images"]}
    ids |= {
        a["image"]
        for r in data["rooms"]
        for it in r["items"]
        for a in it.get("accessories", [])
        if a.get("image")
    }
    ids |= {i for r in data["rooms"] for it in r["items"] for i in it.get("images", [])}
    files = Image.objects.in_bulk(ids)
    data["date"] = date.fromisoformat(data["date"])
    for r in data["rooms"]:
        r["images"] = [files[i] for i in r["images"] if i in files]
        for it in r["items"]:
            it["images"] = [files[i] for i in it.get("images", []) if i in files]
            for a in it.get("accessories", []):
                a["image"] = files.get(a.get("image"))
    return data


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
