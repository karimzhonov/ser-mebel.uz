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
    Section(
        "call_center_manager",
        "Sotuv",
        "Call-center — barcha xodimlar ishlari",
        (),
        edit=False,
        hint="Hamma xodimlarning vazifalarini ko'radi va filtrlaydi",
    ),
    Section(
        "flag_call_center",
        "Sotuv",
        "Call-center operatori",
        (),
        edit=False,
        hint="Arizalar va telefon ishlari uning ro'yxatida chiqadi. «Call-center»da «O'zgartirish» ham kerak",
    ),
    Section("clients", "Sotuv", "Mijozlar", ("client.client",)),
    Section(
        "meterings",
        "O'lchov",
        "O'lchovlar",
        ("metering.metering",),
        extra=("metering.change_status",),
    ),
    Section(
        "metering_booker",
        "O'lchov",
        "O'lchovga yozish (arizadan)",
        (),
        edit=False,
        hint="Mijozni arizadan zamerga yozadi. O'lchovni ko'rish uchun «O'lchovlar»da «Ko'rish», "
        "o'zgartirish uchun «O'zgartirish» kerak",
    ),
    Section(
        "metering_measurer",
        "O'lchov",
        "Zamerchi",
        (),
        edit=False,
        hint="Zamerlar unga biriktiriladi, bot eslatib turadi. «O'lchovlar»da kamida «Ko'rish» ham kerak",
    ),
    Section(
        "metering_manager",
        "O'lchov",
        "Bosh menejer (zamer, dizayn, narx)",
        (),
        edit=False,
        hint="Hamma zamer, dizayn va narx ishlarini ko'radi, ijrochi va muddatni o'zgartiradi, bosh sahifada umumiy ko'rinish",
    ),
    Section("designs", "O'lchov", "Dizayn", ("design.design", "design.designtype")),
    Section(
        "design_designer",
        "O'lchov",
        "Dizayner",
        (),
        edit=False,
        hint="Dizaynlar unga biriktiriladi, bot eslatadi. «Dizayn»da «O'zgartirish» ham kerak",
    ),
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
    Section(
        "metering_presenter",
        "O'lchov",
        "Menejer (dizayn/narxni mijozga ko'rsatadi)",
        (),
        edit=False,
        hint="Dizayn va Narx hisoblashda kamida «Ko'rish» ham kerak",
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
    Section(
        "flag_detailing",
        "Buyurtmalar",
        "Konstruktor (detalirovka ijrochisi)",
        (),
        edit=False,
        hint="Detalirovka vazifalari unga biriktiriladi va Telegram'ga xabar boradi",
    ),
    Section(
        "flag_rover",
        "Buyurtmalar",
        "Rover (ijrochi)",
        (),
        edit=False,
        hint="Rover vazifalari va Telegram xabarlari",
    ),
    Section(
        "flag_painter",
        "Buyurtmalar",
        "Molyar (ijrochi)",
        (),
        edit=False,
        hint="Bo'yash vazifalari va Telegram xabarlari",
    ),
    Section(
        "flag_assembly",
        "Buyurtmalar",
        "Sborkachi (ijrochi)",
        (),
        edit=False,
        hint="Yig'ish vazifalari unga biriktiriladi va Telegram xabarlari",
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
_SINGLE = {
    "order_price": "order.view_order_price",
    "finance_all": "accounting.view_all_operations",
    "call_center_manager": "call_center.manage_invoice",
    "flag_call_center": "oauth.user_call_center",
    "flag_detailing": "oauth.user_detailing",
    "flag_rover": "oauth.user_rover",
    "flag_painter": "oauth.user_painter",
    "flag_assembly": "oauth.user_assembly",
    "metering_booker": "metering.add_metering",
    "metering_measurer": "oauth.user_metering",
    "metering_manager": "metering.manage_metering",
    "design_designer": "oauth.user_design",
    "metering_presenter": "metering.present_to_client",
}


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


def _sections_report(own: set[str], groups: set[str]) -> list[dict]:
    return [
        {
            "key": s.key,
            "title": s.title,
            "label": s.label,
            "hint": s.hint,
            "can_edit": s.edit,
            # one yes/no permission (shown as «Yo'q / Ha» instead of «Ko'rish»)
            "is_flag": s.key in _SINGLE,
            "level": _level(s, own),
            "from_groups": _level(s, groups),
        }
        for s in SECTIONS
    ]


def access(user) -> dict:
    from warehouse.services import is_keeper

    own = _names(user.user_permissions.all())
    groups = _names(Permission.objects.filter(group__user=user))
    return {
        "is_superuser": user.is_superuser,
        "is_keeper": is_keeper(user),
        "sections": _sections_report(own, groups),
    }


def _validate_levels(levels: dict) -> dict:
    by_key = {s.key: s for s in SECTIONS}
    for key, lvl in levels.items():
        if key not in by_key:
            raise ServiceError(f"Noma'lum bo'lim: {key}")
        if lvl not in LEVELS or (lvl == "edit" and not by_key[key].edit):
            raise ServiceError(f"«{by_key[key].label}»: noto'g'ri daraja")
    return by_key


def _wanted(levels: dict, own: set[str], by_key: dict) -> tuple[set[str], set[str]]:
    """(the permission names to hold after, the ones this change grants)."""
    # «O'lchovga yozish» is the section's own add permission: whoever had it only through
    # «O'zgartirish» loses it with the section, not becomes a booker by accident
    if (
        "meterings" in levels
        and "metering_booker" not in levels
        and _level(by_key["meterings"], own) == "edit"
    ):
        levels = {**levels, "metering_booker": "none"}
    target = {s.key: levels.get(s.key) or _level(s, own) for s in SECTIONS}
    drop = set().union(*(by_key[k].all_perms() | _view(by_key[k]) for k in levels))
    keep = set().union(
        *(_required(s, target[s.key]) for s in SECTIONS if target[s.key] in ("view", "edit"))
    )
    return (own - drop) | keep, keep


def _perm_objects(names: set[str]) -> dict:
    return {
        f"{p.content_type.app_label}.{p.codename}": p
        for p in Permission.objects.select_related("content_type").filter(
            content_type__app_label__in={x.split(".")[0] for x in names}
        )
    }


def _forget_perm_cache(user) -> None:
    # Django caches permissions on the instance
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)


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
    by_key = _validate_levels(levels)
    own = _names(user.user_permissions.all())
    wanted, keep = _wanted(levels, own, by_key)
    perms = _perm_objects(wanted | own)
    with transaction.atomic():
        user.user_permissions.set([perms[x] for x in wanted if x in perms])
        if keep and not user.is_staff:
            user.is_staff = True  # a section without panel login would be useless
            user.save(update_fields=["is_staff"])
    _forget_perm_cache(user)
    return access(user)


# --- Groups = roles: the same sections, stored on group.permissions --------------------


def group_access(group) -> dict:
    """The group's section levels (same payload as access(); `from_groups` is none)."""
    own = _names(group.permissions.all())
    return {
        "is_superuser": False,
        "is_keeper": False,
        "sections": _sections_report(own, set()),
    }


def set_group_access(group, levels: dict) -> dict:
    """Like set_access, on the group's permissions. Members who must now log in to the
    panel become staff."""
    from oauth.services import _refuse_keeper

    _refuse_keeper(group)
    by_key = _validate_levels(levels)
    own = _names(group.permissions.all())
    wanted, keep = _wanted(levels, own, by_key)
    perms = _perm_objects(wanted | own)
    with transaction.atomic():
        group.permissions.set([perms[x] for x in wanted if x in perms])
        if wanted:
            group.user_set.filter(is_staff=False).update(is_staff=True)
    for member in group.user_set.all():
        _forget_perm_cache(member)
    return group_access(group)
