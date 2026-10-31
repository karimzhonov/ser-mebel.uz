"""Per-person section access for «Tizim → Xodimlar»: for every section of the panel
a level — none / view (ko'rish) / edit (o'zgartirish).

A level is a set of ordinary Django permissions stored on the user
(`user.user_permissions`), so every existing check — ModelPermissions on the API,
require_perm() in actions, can() in the SPA — enforces it as is. Group permissions
keep working on top; they are only reported here, never changed.

Section → permissions:
- view = view_<model> of its own models + `reads` (what its pages also load);
- edit = view + add/change/delete of its own models + `extra` (custom perms).
A section with `edit=False` is view-only here (e.g. the warehouse: only the keeper books).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.models import Permission
from django.db import transaction

from core.exceptions import ServiceError

LEVELS = ("none", "view", "edit")


@dataclass(frozen=True)
class Section:
    key: str
    title: str  # menu group
    label: str
    models: tuple[str, ...]  # "app.model": full CRUD on edit
    reads: tuple[str, ...] = ()  # "app.model": view only, part of «view»
    extra: tuple[str, ...] = ()  # "app.codename": part of «edit»
    edit: bool = True
    hint: str = ""

    def view_perms(self) -> set[str]:
        return {_perm(m, "view") for m in self.models + self.reads}

    def edit_perms(self) -> set[str]:
        out = self.view_perms() | set(self.extra)
        for m in self.models:
            out |= {_perm(m, a) for a in ("add", "change", "delete")}
        return out

    def all_perms(self) -> set[str]:
        return self.edit_perms() if self.edit else self.view_perms()


def _perm(model: str, action: str) -> str:
    app, name = model.split(".")
    return f"{app}.{action}_{name}"


CATALOG = ("price.objecttype", "price.inventorytype", "price.inventory", "price.roomtype")
HR_READS = (
    "hr.employee",
    "hr.workgroup",
    "hr.holiday",
    "hr.holidaydecision",
    "hr.leave",
    "hr.pointadjustment",
    "hr.winner",
)

SECTIONS: tuple[Section, ...] = (
    Section("call_center", "Sotuv", "Call-center", ("call_center.invoice",)),
    Section("clients", "Sotuv", "Mijozlar", ("client.client",)),
    Section(
        "meterings",
        "O'lchov",
        "O'lchovlar",
        ("metering.metering",),
        extra=("metering.change_status",),
    ),
    Section("designs", "O'lchov", "Dizayn", ("design.design", "design.designtype")),
    Section(
        "prices",
        "O'lchov",
        "Narx hisoblash",
        (
            "price.price",
            "price.calculate",
            "price.room",
            "price.roomimage",
            "price.calcaccessory",
            "price.priceversion",
            "price.inventoryincalculate",
        ),
        reads=CATALOG,
        hint="Katalogni ham ko'radi (narx tanlash uchun)",
    ),
    Section("catalog", "O'lchov", "Mahsulotlar (katalog)", CATALOG),
    Section(
        "orders",
        "Buyurtmalar",
        "Buyurtmalar",
        ("order.order",),
        extra=("order.change_status_order", "order.reverse_status_order"),
    ),
    Section(
        "order_price",
        "Buyurtmalar",
        "Buyurtma narxlari",
        (),
        extra=(),
        reads=(),
        edit=False,
        hint="Buyurtmalarda summa va to'lovlar ko'rinadi",
    ),
    Section("detailing", "Buyurtmalar", "Detalirovka", ("detailing.detailing",)),
    Section("rover", "Buyurtmalar", "Rover", ("rover.rover",)),
    Section("painter", "Buyurtmalar", "Molyar", ("painter.painter", "painter.paintertype")),
    Section(
        "assembly",
        "Buyurtmalar",
        "Yig'ish / O'rnatish",
        ("assembly.assembly",),
        extra=("assembly.manager",),
        hint="O'zgartirish = menejer: hamma ishlarni ko'radi va taqsimlaydi",
    ),
    Section("factories", "Buyurtmalar", "Zavodlar", ("order.factory",)),
    Section(
        "finance",
        "Moliya",
        "Moliya",
        (
            "accounting.operation",
            "accounting.monthreport",
            "accounting.moneyrequest",
            "accounting.orderbonus",
            "accounting.financecategory",
            "accounting.worker",
            "accounting.financecar",
            "accounting.manualorder",
            "accounting.warrantyletter",
            "accounting.siteentrytask",
            "accounting.clientfeedback",
        ),
    ),
    Section(
        "finance_all",
        "Moliya",
        "Moliya — barcha hamyonlar",
        (),
        edit=False,
        hint="Belgilanmasa, faqat o'z amallarini ko'radi",
    ),
    Section("finance_settings", "Moliya", "Moliya sozlamalari", ("oauth.telegrammember",)),
    Section(
        "warehouse",
        "Ombor",
        "Ombor (qoldiq, kirim / chiqim)",
        ("warehouse.product", "warehouse.movement"),
        edit=False,
        hint="Kirim / chiqimni faqat omborchi qiladi",
    ),
    Section(
        "hr_attendance",
        "HR",
        "Davomat, jurnal, reyting",
        ("hr.attendance",),
        reads=HR_READS,
        extra=(
            "hr.add_leave",
            "hr.change_leave",
            "hr.delete_leave",
            "hr.add_pointadjustment",
            "hr.change_pointadjustment",
            "hr.delete_pointadjustment",
            "hr.add_winner",
        ),
    ),
    Section("hr_employees", "HR", "HR xodimlar", ("hr.employee",), reads=("hr.workgroup",)),
    Section(
        "hr_calendar", "HR", "Bayram va ta'tillar", ("hr.holiday", "hr.holidaydecision", "hr.leave")
    ),
    Section("hr_settings", "HR", "Davomat sozlamalari", ("hr.workgroup", "hr.hrsetting")),
    Section(
        "files",
        "Umumiy",
        "Fayllar (papkalar)",
        ("filer.folder", "filer.file", "filer.image"),
    ),
    Section("discussion", "Umumiy", "Izohlar (chat)", ("discussion.discussionmessage",)),
)

# view-only sections that are one custom permission
_SINGLE = {"order_price": "order.view_order_price", "finance_all": "accounting.view_all_operations"}


def _view(sec: Section) -> set[str]:
    return {_SINGLE[sec.key]} if sec.key in _SINGLE else sec.view_perms()


def _edit(sec: Section) -> set[str]:
    return _view(sec) if not sec.edit else sec.edit_perms()


def _required(sec: Section, level: str) -> set[str]:
    return {"none": set(), "view": _view(sec), "edit": _edit(sec)}[level]


def _level(sec: Section, perms: set[str]) -> str:
    if sec.edit and _edit(sec) <= perms:
        return "edit"
    if _view(sec) <= perms:
        return "view"
    if (_edit(sec) | _view(sec)) & perms:
        return "custom"  # set by hand in the old admin: kept until changed here
    return "none"


def _names(qs) -> set[str]:
    return {f"{a}.{c}" for a, c in qs.values_list("content_type__app_label", "codename")}


def access(user) -> dict:
    from warehouse.services import is_keeper

    own = _names(user.user_permissions.all())
    groups = _names(Permission.objects.filter(group__user=user))
    return {
        "is_superuser": user.is_superuser,
        "is_keeper": is_keeper(user),
        "sections": [
            {
                "key": s.key,
                "title": s.title,
                "label": s.label,
                "hint": s.hint,
                "can_edit": s.edit,
                "level": _level(s, own),
                "from_groups": _level(s, groups),
            }
            for s in SECTIONS
        ],
    }


def set_access(user, levels: dict) -> dict:
    """Set the levels given ({section: none|view|edit}); sections left out keep what
    they have. Shared permissions (e.g. the catalog's view, used by «Narx hisoblash»
    too) stay while another section still needs them."""
    from warehouse.services import is_keeper

    if user.is_superuser:
        raise ServiceError("Administrator hamma bo'limni ko'radi — huquq berish shart emas")
    if is_keeper(user):
        raise ServiceError(
            "Bu xodim — omborchi. Uning huquqlari Ombor → Omborchi sahifasida boshqariladi."
        )
    by_key = {s.key: s for s in SECTIONS}
    for key, lvl in levels.items():
        if key not in by_key:
            raise ServiceError(f"Noma'lum bo'lim: {key}")
        if lvl not in LEVELS or (lvl == "edit" and not by_key[key].edit):
            raise ServiceError(f"«{by_key[key].label}»: noto'g'ri daraja")

    own = _names(user.user_permissions.all())
    target = {s.key: levels.get(s.key) or _level(s, own) for s in SECTIONS}
    drop = set().union(*(by_key[k].all_perms() | _view(by_key[k]) for k in levels))
    keep = set().union(
        *(_required(s, target[s.key]) for s in SECTIONS if target[s.key] in ("view", "edit"))
    )
    wanted = (own - drop) | keep

    perms = {
        f"{p.content_type.app_label}.{p.codename}": p
        for p in Permission.objects.select_related("content_type").filter(
            content_type__app_label__in={x.split(".")[0] for x in wanted | own}
        )
    }
    with transaction.atomic():
        user.user_permissions.set([perms[x] for x in wanted if x in perms])
        if keep and not user.is_staff:
            user.is_staff = True  # a section without panel login would be useless
            user.save(update_fields=["is_staff"])
    # Django caches permissions on the instance
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    return access(user)
