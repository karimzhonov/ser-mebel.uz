from django.db import transaction
from filer.models.foldermodels import Folder

from core.exceptions import ServiceError, ServiceForbidden

MANAGE = "metering.manage_metering"


def create_price_folder(price) -> None:
    """Create the Filer folder for this Price nested under its Metering's folder.

    No-ops when the Price has no linked Metering (metering=None is a valid
    state — see PriceAdmin, which allows creating a Price without a metering).
    """
    if price.metering is None:
        return

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

    from .models import Calculate, Price

    amount = 0
    for calc in Calculate.objects.filter(price=price):
        if calc.amount is not None:
            amount += calc.amount.amount
    price.price = Money(amount, currency="USD")
    # not a full save(): stage / rev / due_at may have moved under this request
    Price.objects.filter(pk=price.pk).update(price=price.price)
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


def create_price(metering, *, user, due_at, days, by=None):
    """A Price in work for the metering; the pricer, if any, is told at once (it starts
    together with the design). `days` = the deadline's length in days. Call inside the
    caller's transaction."""
    from metering import events
    from metering import services as M

    from .models import Price

    with transaction.atomic():
        price = Price(
            metering=metering,
            user=user,
            stage="work",
            due_at=due_at,
            assigned_at=M._now(),
            duration_days=days,
        )
        price._history_user = by
        price.save()
        if user is not None:
            events.offer_assigned(price, "price", how="new")
            M.queue_offer_sms(price, "price", "assigned")
    return price


# --- The approximate price on a lead (ariza) ------------------------------------------
# Owner's rule: the operator, the manager and the zamerchi may add an approximate price to
# a lead to tell the client; not needed -> delete it; needed -> it goes on with the lead
# and «Bajarildi» gives it to the chosen manager to finish (no new price is made).


def can_estimate(user) -> bool:
    """Who may add / edit / delete a lead's approximate price, without the price rights:
    whoever WORKS the lead or its zamer — the operator (changes leads), the zamerchi, the
    manager / bosh menejer, a pricer. A read-only viewer may not."""
    if user is None or not user.is_active:
        return False
    return user.is_superuser or any(
        user.has_perm(p)
        for p in (
            "call_center.change_invoice",
            "oauth.user_metering",
            "metering.present_to_client",
            "metering.manage_metering",
            "price.change_price",
        )
    )


def can_open_estimate(user, price) -> bool:
    """«Only for that price»: an estimate is opened by who may make estimates AND sees its
    lead or zamer (a plain zamerchi sees only their own zamers)."""
    from metering.services import metering_queryset_for

    if not (is_estimate(price) and can_estimate(user)):
        return False
    if user.is_superuser:
        return True
    if price.metering_id is not None and metering_queryset_for(user).filter(
        pk=price.metering_id
    ).exists():
        return True
    return price.invoice_id is not None and user.has_perm("call_center.view_invoice")


def is_estimate(price) -> bool:
    from metering.constants import PRICE_ESTIMATE

    return price is not None and price.stage == PRICE_ESTIMATE


def create_estimate(*, by, invoice=None, metering=None):
    """The approximate price of a lead (from the lead) or of a zamer (from the zamer
    page): one per lead / zamer. Made on a lead that already has a zamer, it is joined to
    that zamer (when it has no price yet) — «Bajarildi» then hands it on."""
    from metering.constants import PRICE_ESTIMATE
    from metering.models import Metering

    from .models import Price

    if not can_estimate(by):
        raise ServiceForbidden("Taxminiy narx qo'shish huquqi yo'q")
    from metering import services as M

    if metering is not None and invoice is None:
        invoice = metering.invoice
    with transaction.atomic():
        if invoice is not None:  # lock order: Invoice -> Metering
            type(invoice).objects.select_for_update().get(pk=invoice.pk)
            if Price.objects.filter(invoice=invoice, stage=PRICE_ESTIMATE).exists():
                raise ServiceError("Bu arizada taxminiy narx bor")
            if metering is None:
                metering = Metering.objects.filter(invoice=invoice).first()
                if metering is not None and metering.status == "dont_need":
                    metering = None  # a cancelled zamer: the estimate waits on the lead
        if metering is not None:
            metering = M._lock(metering)
            if metering.status in ("done", "sold_out", "dont_need"):
                raise ServiceError("Zamer yakunlangan — narxni menejer hisoblaydi")
            if Price.objects.filter(metering=metering).exists():
                raise ServiceError("Bu mijozning narxi allaqachon hisoblanmoqda")
        if invoice is not None:
            # a re-booked lead: its old (finished) price lets go of the lead
            Price.objects.filter(invoice=invoice).exclude(stage=PRICE_ESTIMATE).update(
                invoice=None
            )
        client = invoice.client if invoice is not None else metering.client
        price = Price(
            invoice=invoice,
            metering=metering,
            stage=PRICE_ESTIMATE,
            desc=(client.fio if client is not None else "") or None,
        )
        price._history_user = by
        price.save()
    return price


def delete_estimate(price, *, by) -> None:
    """Not needed: drop the approximate price with its calculations. Only while it is
    still an estimate (until the zamer is finished)."""
    if not can_estimate(by):
        raise ServiceForbidden("Taxminiy narxni o'chirish huquqi yo'q")
    with transaction.atomic():
        from .models import Price

        locked = Price.objects.select_for_update().filter(pk=price.pk).first()
        if locked is None:
            return
        done = locked.metering_id is not None and locked.metering.status in ("done", "sold_out")
        if not is_estimate(locked) or done:
            raise ServiceError(
                "Zamer yakunlangan — narx endi menejerning vazifasi, uni faqat tahrirlash mumkin"
            )
        locked.delete()


def attach_estimate(metering, invoice, *, by=None) -> None:
    """A zamer was booked for the lead: its approximate price goes with it. Inside the
    caller's transaction."""
    from metering.constants import PRICE_ESTIMATE

    from .models import Price

    est = (
        Price.objects.select_for_update()
        .filter(invoice=invoice, stage=PRICE_ESTIMATE)
        .exclude(metering=metering)
        .first()
    )
    if est is None or Price.objects.filter(metering=metering).exists():
        return
    est.metering = metering
    est._history_user = by
    est.save(update_fields=["metering"])
    if est.folder_id is None:  # made on the lead alone: its folder goes under the zamer's
        create_price_folder(est)


def estimate_to_task(price, *, user, due_at, days, by=None):
    """«Bajarildi»: the zamer's approximate price becomes the chosen manager's price task
    (stage work, deadline) — they finish it instead of starting a new one. Inside the
    caller's transaction, row locked."""
    from metering import events
    from metering import services as M

    price.stage = "work"
    price.user = user
    price.due_at = due_at
    price.assigned_at = M._now()
    price.duration_days = days
    price.rev += 1
    price._history_user = by
    price.save(update_fields=["stage", "user", "due_at", "assigned_at", "duration_days", "rev"])
    if user is not None:
        events.offer_assigned(price, "price", how="new")
        M.queue_offer_sms(price, "price", "assigned")
    return price


def can_work_price(user, price) -> bool:
    """May press «Tayyor» / move the deadline: the pricer, a price boss, a superuser;
    anyone who can change prices while nobody is assigned."""
    if user is None:
        return False
    if user.is_superuser or user.has_perm(MANAGE):
        return True
    if price.user_id is not None:
        return price.user_id == user.pk
    return user.has_perm("price.change_price")


def mark_price_done(price, *, by):
    """«Tayyor» (site only): the calculation goes to the manager, who shows it to the
    client."""
    from metering import services as M

    if is_estimate(price):
        raise ServiceError("Taxminiy narx — zamer yakunlanganda u menejerga beriladi")
    if price.metering_id is None:
        # a calculation made in the admin without a zamer: nobody to show it to
        if price.done:
            raise ServiceError("Allaqachon bajarilgan")
        price.done = True
        price.stage = "approved"
        price.done_at = M._now()
        price.done_by = by
        price._history_user = by
        price.save(update_fields=["done", "stage", "done_at", "done_by"])
        return price
    with transaction.atomic():
        m, _, _, locked = M.offer_locked(price, "price")
        if not can_work_price(by, locked):
            raise ServiceForbidden("Bu hisob sizga biriktirilmagan")
        if locked.stage != "work":
            raise M.offer_stage_error(locked.stage)
        M.offer_ready(locked, "price", m, by=by, now=M._now())
    return M._copy_back(price, locked, ["done", "stage", "done_at", "done_by", "rev"])


def set_price_due(price, *, by, due_at=None, preset=None, text=None):
    from metering import services as M

    return M.move_offer_due(
        price, "price", by=by, can_work=can_work_price, due_at=due_at, preset=preset, text=text
    )


def set_pricer(price, *, by, user):
    from metering import services as M

    return M.reassign_offer(price, "price", by=by, user=user, boss_perm=MANAGE, pool=M.pricers())


def unassigned_prices():
    """Prices in work that nobody calculates (from before the managers got the price
    job): oldest first."""
    from .models import Price

    return Price.objects.filter(stage="work", user__isnull=True).order_by("created_at", "pk")


def assign_prices(*, by, user, due_at, count=None) -> dict:
    """Admin / bosh menejer: give the `count` oldest unassigned prices in work (all when
    None) to the manager `user` with the deadline `due_at`. With a zamer the manager gets
    the bot card (like «Bajarildi») and becomes the zamer's manager when it has none, so
    «tayyor» comes back to them. Returns {"assigned", "left"}."""
    from metering import services as M

    from .models import Price

    if not (by.is_superuser or by.has_perm(MANAGE)):
        raise ServiceForbidden("Narxni menejerga berish huquqi yo'q")
    if not M.pricers().filter(pk=user.pk).exists():
        raise ServiceError(
            "Bu xodimda narx huquqi yo'q — Xodimlar → Lavozimlar: lavozimida «Narx "
            "hisoblash» bo'limini (o'zgartirish) yoqing",
            "user",
        )
    if due_at is None:
        raise ServiceError("Muddatni tanlang", "due_at")
    if count is not None and count < 1:
        raise ServiceError("Nechta ish berishni yozing", "count")
    ids = list(unassigned_prices().values_list("pk", flat=True)[:count])
    now = M._now()
    assigned = 0
    for pk in ids:
        with transaction.atomic():
            price = Price.objects.select_related("metering").get(pk=pk)
            if price.metering_id is None:  # a price without a zamer: no bot card to show
                n = Price.objects.filter(pk=pk, stage="work", user__isnull=True).update(
                    user=user, due_at=due_at, assigned_at=now
                )
                assigned += n
                continue
            m, _, _, row = M.offer_locked(price, "price")
            if row.stage != "work" or row.user_id is not None:
                continue  # taken meanwhile
            row.due_at = due_at
            row.rev += 1
            row._history_user = by
            row.save(update_fields=["due_at", "rev"])
            if m.manager_id is None:
                m.manager = user
                m.save(update_fields=["manager"])
            M._hand_over(row, "price", user, by=by, now=now)
            assigned += 1
    return {"assigned": assigned, "left": unassigned_prices().count()}


def delete_unassigned_prices(*, by, ids) -> dict:
    """Admin only: delete old prices nobody calculates (still in work, no assignee) that
    are not needed any more — with their calculations, rooms and versions. A price whose
    zamer already became an order is kept. Returns {"deleted", "kept"}."""
    if not by.is_superuser:
        raise ServiceForbidden("Narxni faqat administrator o'chiradi")
    wanted = {int(i) for i in ids or []}
    if not wanted:
        raise ServiceError("O'chiriladigan narxlarni tanlang", "ids")
    from .models import Price

    with transaction.atomic():
        ok = list(
            unassigned_prices()
            .filter(pk__in=wanted, metering__order__isnull=True)
            .values_list("pk", flat=True)
        )
        # re-checked in the delete itself: nobody took it meanwhile
        Price.objects.filter(pk__in=ok, stage="work", user__isnull=True).delete()
    return {"deleted": len(ok), "kept": len(wanted) - len(ok)}


def record_price_answer(price, *, by, answer, comment="", due_at=None):
    """The manager's record of what the client said: approved | recalc | declined.
    Returns {"task": price, "closed_tasks": n}."""
    from call_center.constants import SolutionChoice
    from call_center.services import close_lead_from_offer
    from metering import events
    from metering import services as M
    from metering.constants import ClientResult

    comment = M.offer_answer_prelude(answer, comment, ("approved", "recalc", "declined"))
    closed = 0
    with transaction.atomic():
        m, _, _, locked = M.offer_locked(price, "price")
        M.offer_check_answerable(locked, m, by, "price")
        now = M._now()
        new_due = None
        answered_round = locked.round
        locked._history_user = by
        if answer == "approved":
            locked.stage = "approved"
            locked.rev += 1
            locked.save(update_fields=["stage", "rev"])
            m.client_result = ClientResult.agreed
            m._history_user = by
            m.save(update_fields=["client_result"])
        elif answer == "recalc":
            new_due = M.offer_send_back(
                locked,
                "price",
                m,
                by=by,
                now=now,
                comment=comment,
                due_at=due_at,
                fix_cfg="PRICE_FIX_DAYS",
            )
        else:
            locked.stage = "declined"
            locked.done = False  # invariant: done == stage in (review, approved)
            locked.rev += 1
            locked.save(update_fields=["stage", "done", "rev"])
            m.client_result = ClientResult.price_declined
            m._history_user = by
            m.save(update_fields=["client_result"])
        M.offer_store_answer(
            locked,
            "price",
            m,
            by=by,
            answer=answer,
            comment=comment,
            round_=answered_round,
            due_at=new_due,
            log=answer != "declined",
        )
        if answer == "declined" and m.invoice_id is not None:
            closed = close_lead_from_offer(
                m.invoice,
                by=by,
                solution=SolutionChoice.price_problem,
                reason=comment,
                metering_id=m.pk,
                event="price_declined",
            )
        M.offer_answered(locked, "price", m, by=by, answer=answer)
        if answer == "approved":
            # the manager if they may make orders, else everybody who may
            if m.manager is not None and m.manager.has_perm("order.add_order"):
                makers = [m.manager]
            else:
                makers = list(M.order_creators())
            events.offer_order_ready(locked, to_users=makers)
    M._copy_back(price, locked, ["stage", "done", "round", "due_at", "rev"])
    return {"task": price, "closed_tasks": closed}
