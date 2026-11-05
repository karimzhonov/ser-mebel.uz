import logging

from django.db import models
from django.urls import reverse_lazy

from core.sms import absolute_url, format_phone, send_bulk_sms

logger = logging.getLogger(__name__)

TEST_MESSAGE_TEXT = "Тестовое сообщение — Telegram уведомления работают."


def send_test_telegram_messages(users) -> tuple[int, int, int]:
    """Send a test Telegram message to each of `users`.

    Returns (sent, without_telegram, failed). One user's bot-server failure must not
    abort the rest of the batch, so every send is guarded — User.send_message() posts
    to the bot synchronously, and the admin request is blocked for the whole loop.
    """
    sent = without_telegram = failed = 0
    for user in users:
        if not user.telegram_id:
            without_telegram += 1
            continue
        try:
            user.send_message(text=TEST_MESSAGE_TEXT)
        except Exception:
            logger.exception("Test Telegram message failed for user %s", user.pk)
            failed += 1
        else:
            sent += 1
    return sent, without_telegram, failed


def staff_with_permission(codename: str):
    from .models import User

    return User.objects.filter(
        models.Q(user_permissions__codename=codename)
        | models.Q(groups__permissions__codename=codename),
        is_active=True,
    ).distinct()


def notify_staff(
    *,
    permission,
    path_name,
    kwargs,
    telegram_text="Оповещение о заказе",
    sms_template=None,
    sms_context=None,
    telegram=True,
) -> None:
    codename = permission.split(".")[-1]
    url = reverse_lazy(path_name, kwargs=kwargs)
    sms_batch = []
    for user in staff_with_permission(codename):
        if telegram:
            user.send_message(url, text=telegram_text)
        if sms_template:
            phone = format_phone(user.phone)
            if phone:
                text = sms_template.format(
                    xodim_ism=user.name or "", url=absolute_url(url), **(sms_context or {})
                )
                sms_batch.append({"phone": phone, "text": text})
    send_bulk_sms(sms_batch)


def verify_telegram_init_data(init_data: str, bot_token: str, max_age: int | None = None):
    """Validate Telegram WebApp `initData` and return its `user` dict, or None.

    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    secret = HMAC_SHA256(key="WebAppData", msg=bot_token); the payload's `hash` must
    equal HMAC_SHA256(key=secret, msg=data_check_string), where data_check_string is
    every other field as "key=value", sorted by key, joined by "\\n".

    This proves who the Telegram user is (unlike the removed bare ?telegram_id=
    admin login). It does NOT prove that this Telegram account belongs to the staff
    user it is linked to — that depends on the bot's /start linking.
    """
    import hashlib
    import hmac
    import json
    import time
    from urllib.parse import parse_qsl

    if not init_data or not bot_token:
        return None
    try:
        fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    received_hash = fields.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        return None

    if max_age:
        try:
            auth_date = int(fields.get("auth_date", "0"))
        except ValueError:
            return None
        if time.time() - auth_date > max_age:
            return None

    try:
        user = json.loads(fields.get("user", ""))
    except ValueError:
        return None
    if not isinstance(user, dict) or "id" not in user:
        return None
    return user


def users_with_perm(app_label: str, codename: str):
    """Active users holding app_label.codename directly or through a group, plus
    superusers (they hold every permission)."""
    from .models import User

    perm = models.Q(
        user_permissions__codename=codename,
        user_permissions__content_type__app_label=app_label,
    ) | models.Q(
        groups__permissions__codename=codename,
        groups__permissions__content_type__app_label=app_label,
    )
    return User.objects.filter(is_active=True).filter(perm | models.Q(is_superuser=True)).distinct()


def user_by_telegram(telegram_id):
    """The active panel user linked to this Telegram account (bot -> site identity)."""
    from .models import User

    try:
        tg = int(telegram_id)
    except (TypeError, ValueError):
        return None
    return User.objects.filter(telegram_id=tg, is_active=True, is_staff=True).order_by("pk").first()


def notify_user(user, *, url, telegram_text, sms_template=None, sms_context=None) -> None:
    """Telegram + SMS to ONE person (the assigned executor), not to a whole role.
    A failed send is logged, never raised: the task itself is already saved."""
    try:
        user.send_message(url, text=telegram_text)
    except Exception:
        logger.exception("Telegram notification failed for user %s", user.pk)
    if sms_template:
        phone = format_phone(user.phone)
        if phone:
            text = sms_template.format(
                xodim_ism=user.name or "", url=absolute_url(url), **(sms_context or {})
            )
            send_bulk_sms([{"phone": phone, "text": text}])


def link_telegram(token, telegram_id: int):
    """Link a Telegram account to the site user named by a `/start` link payload.

    `token` is the signed payload built by core.telegram.link_token (`u{pk}_{hmac10}`);
    anything else (including the old plain-digit format) is refused. Returns the User,
    or None for a bad signature, an unknown or inactive user. The Telegram id is moved here if another user still had it (login by
    telegram_id must stay unambiguous). Called by POST /api/v1/bot/link/ - the bot no
    longer writes oauth_user itself.
    """
    from django.db import transaction

    from core.telegram import parse_link_token

    from .models import User

    pk = parse_link_token(token)
    if pk is None:
        return None
    with transaction.atomic():
        user = User.objects.select_for_update().filter(pk=pk, is_active=True).first()
        if user is None:
            return None
        User.objects.filter(telegram_id=int(telegram_id)).exclude(pk=pk).update(telegram_id=None)
        if user.telegram_id != int(telegram_id):
            user.telegram_id = int(telegram_id)
            user.save(update_fields=["telegram_id"])
    return user


# Deleting a staff account must not silently take work history with it. These are
# the only rows that may disappear (or be unlinked) together with the user.
_USER_DELETE_OK = {
    "oauth.user",
    "admin.logentry",
    "token_blacklist.outstandingtoken",
    "token_blacklist.blacklistedtoken",
}
_USER_HAS_HISTORY = (
    "Bu xodimning ish tarixi bor (yig'ish, izohlar …) — "
    "o'chirish o'rniga «Faol» belgisini olib qo'ying."
)


def delete_user(actor, user) -> None:
    """Admin removes a staff account (e.g. added by mistake).

    Refused for yourself, for the last active superuser, and when the user owns work
    records that would be deleted with them (assembly jobs, discussion messages …) —
    then the account should be switched off («Faol» unticked) instead.
    """
    from django.db import transaction
    from django.db.models.deletion import Collector, ProtectedError, RestrictedError

    from core.exceptions import ServiceError

    from .models import User

    if actor.pk == user.pk:
        raise ServiceError("O'zingizni o'chira olmaysiz.")
    if (
        user.is_superuser
        and not User.objects.filter(is_superuser=True, is_active=True).exclude(pk=user.pk).exists()
    ):
        raise ServiceError("Oxirgi administratorni o'chirib bo'lmaydi.")

    collector = Collector(using="default")
    try:
        collector.collect([user])
    except (ProtectedError, RestrictedError):
        raise ServiceError(_USER_HAS_HISTORY)
    # Rows deleted with the user: `data` (loaded objects) + `fast_deletes` (querysets).
    doomed = [(m, bool(objs)) for m, objs in collector.data.items()]
    doomed += [(qs.model, qs.exists()) for qs in collector.fast_deletes]
    for model, has_rows in doomed:
        if not has_rows or model._meta.auto_created:  # groups / permissions link rows
            continue
        if model._meta.label_lower not in _USER_DELETE_OK:
            raise ServiceError(_USER_HAS_HISTORY)

    with transaction.atomic():
        user.delete()


# --- Groups = roles (Operator, Dizayner, Bosh menejer, ...) --------------------------


def _group_name(name) -> str:
    from core.exceptions import ServiceError

    name = " ".join((name or "").split())
    if not name:
        raise ServiceError("Lavozim nomini kiriting", "name")
    if len(name) > 150:
        raise ServiceError("Lavozim nomi juda uzun", "name")
    return name


def _check_group_name_free(name, *, exclude=None) -> None:
    from django.contrib.auth.models import Group

    from core.exceptions import ServiceError

    qs = Group.objects.filter(name__iexact=name)
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    if qs.exists():
        raise ServiceError("Bunday nomli lavozim bor", "name")


def _refuse_keeper(group=None, user=None) -> None:
    """The omborchi is managed only on the Ombor page (assign_keeper): the role page
    must not become a way around that rule."""
    from core.exceptions import ServiceError
    from warehouse.services import KEEPER_GROUP, is_keeper

    if (group is not None and group.name == KEEPER_GROUP) or (user is not None and is_keeper(user)):
        raise ServiceError("Omborchi Ombor sahifasida boshqariladi", "members")


def create_group(name):
    from django.contrib.auth.models import Group

    name = _group_name(name)
    _check_group_name_free(name)
    return Group.objects.create(name=name)


def rename_group(group, name):
    _refuse_keeper(group)
    name = _group_name(name)
    _check_group_name_free(name, exclude=group)
    group.name = name
    group.save(update_fields=["name"])
    return group


def delete_group(group) -> None:
    """A role with people in it cannot be deleted: move the people out first."""
    from core.exceptions import ServiceError

    _refuse_keeper(group)
    n = group.user_set.count()
    if n:
        raise ServiceError(
            f"Lavozimda {n} nafar xodim bor — avval ularni lavozimdan chiqaring", "members"
        )
    group.delete()


def group_members(group):
    return group.user_set.order_by("name", "phone")


def add_group_member(group, user):
    """Give the user the group's role. The group's permissions need panel login, so the
    person becomes staff when the group has any permission."""
    from django.db import transaction

    _refuse_keeper(group, user)
    with transaction.atomic():
        group.user_set.add(user)
        if not user.is_staff and group.permissions.exists():
            user.is_staff = True
            user.save(update_fields=["is_staff"])
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    return user


def remove_group_member(group, user):
    _refuse_keeper(group, user)
    group.user_set.remove(user)
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    return user


# --- Merging old groups into the default lavozims -------------------------------------

DEFAULT_LAVOZIMS = (
    "Operator",
    "O'lcham oluvchi",
    "Dizayner",
    "Menejer",
    "Bosh menejer",
    "Konstruktor",
    "Molyar",
    "Sborkachi",
    "Rover",
)

# first match wins (a substring of the lower-cased, trimmed name)
_MERGE_RULES = (
    (("производство manager", "bosh", "главный", "glavn"), "Bosh menejer"),
    (("замер", "zamer", "o'lcham", "olcham", "ўлчам"), "O'lcham oluvchi"),
    (("дизайн", "dizayn", "design"), "Dizayner"),
    (("маляр", "моляр", "molyar", "malyar"), "Molyar"),
    (("сборк", "установк", "sborka", "sborch", "ustanovk"), "Sborkachi"),
    (("детал", "конструкт", "konstrukt", "detal"), "Konstruktor"),
    (("ровер", "rover"), "Rover"),
    (("call", "колл", "оператор", "operator"), "Operator"),
    # owner's rule: the price is the managers' job, there is no «Narxchi» any more
    (("narx", "цен", "прайс", "price"), "Menejer"),
    (("менеджер", "menejer", "manager", "menedjer"), "Menejer"),
)
_PERSONAL_WORDS = ("filer", "файл")
PERSONAL_REASON = "Fayllar huquqi — a'zolariga «Fayllar» bo'limi qo'shiladi"
NO_MATCH_REASON = "Mos lavozim topilmadi — o'zingiz tanlang"


def _suggest_lavozim(name: str):
    low = " ".join((name or "").split()).lower()
    if any(w in low for w in _PERSONAL_WORDS):
        return "personal"
    for words, target in _MERGE_RULES:
        if any(w in low for w in words):
            return target
    return None


def _perm_keys(group) -> set:
    return {
        f"{a}.{c}" for a, c in group.permissions.values_list("content_type__app_label", "codename")
    }


def merge_plan() -> dict:
    """What to do with every group that is not a default lavozim (nothing is changed).

    items[].action: «merge» (suggested = target), «rename» (rename_to; suggested stays null) (the group IS the default
    lavozim written differently, e.g. «operator» → «Operator»), «to_personal» (no target:
    permissions go to the members themselves), «choose» (nothing suggested)."""
    from django.contrib.auth.models import Group
    from django.db.models import Count

    from warehouse.services import KEEPER_GROUP

    groups = list(Group.objects.annotate(n=Count("user")).order_by("name"))
    exact = {g.name: g for g in groups if g.name in DEFAULT_LAVOZIMS}
    by_low = {d.lower(): d for d in DEFAULT_LAVOZIMS}
    items = []
    for g in groups:
        if g.name == KEEPER_GROUP or g.name in exact and exact[g.name].pk == g.pk:
            continue
        item = {
            "group": {
                "id": g.pk,
                "name": g.name,
                "member_count": g.n,
                "locked": False,
            },
            "suggested": None,
            "rename_to": None,
            "to_personal": False,
            "action": "choose",
            "reason": NO_MATCH_REASON,
        }
        default = by_low.get(" ".join(g.name.split()).lower())
        if default and default not in exact:
            item.update(
                rename_to=default,
                action="rename",
                reason=f"Bu «{default}» lavozimining o'zi — nomi to'g'rilanadi",
            )
        else:
            guess = default or _suggest_lavozim(g.name)
            if guess == "personal":
                item.update(action="to_personal", to_personal=True, reason=PERSONAL_REASON)
            elif guess in exact:
                t = exact[guess]
                item.update(
                    suggested={"id": t.pk, "name": t.name},
                    action="merge",
                    reason=f"Nomi bo'yicha «{t.name}» lavozimiga mos",
                )
        items.append(item)
    targets = [{"id": g.pk, "name": g.name} for g in groups if g.name in exact]
    return {"items": items, "targets": targets}


def _perm_labels(keys) -> list:
    """Permission codenames → section-level labels (access.py), else «app.codename»."""
    from . import access as A

    keys = set(keys)
    out, left = [], set(keys)
    for sec in A.SECTIONS:
        view, edit = A._view(sec), A._edit(sec)
        if sec.edit and edit <= keys:
            out.append({"key": f"{sec.key}:edit", "label": f"{sec.label} — o'zgartirish"})
            left -= edit
        elif view <= keys and view:
            out.append({"key": f"{sec.key}:view", "label": f"{sec.label} — ko'rish"})
            left -= view
    out += [{"key": k, "label": k} for k in sorted(left)]
    return out


def _merge_checks(source, target=None):
    from core.exceptions import ServiceError
    from warehouse.services import is_keeper

    _refuse_keeper(source)
    if target is not None:
        _refuse_keeper(target)
        if target.pk == source.pk:
            raise ServiceError("Lavozimni o'ziga ko'chirib bo'lmaydi", "target")
    if any(is_keeper(u) for u in source.user_set.all()):
        raise ServiceError("Omborchi Ombor sahifasida boshqariladi", "members")


def merge_preview(source, target=None) -> dict:
    """What a merge would do. `target=None` = «shaxsiy huquq sifatida»."""
    _merge_checks(source, target)
    have = _perm_keys(target) if target is not None else set()
    add = _perm_keys(source) - have
    if _is_operator_lavozim(target):
        add -= {f"metering.{c}" for c in OPERATOR_NEVER}
    return {
        "members": [
            {"id": u.pk, "name": u.name, "phone": str(u.phone)} for u in group_members(source)
        ],
        "add_to_target": _perm_labels(add),
        "target_member_count": target.user_set.count() if target is not None else None,
    }


# owner's rule: the operator books a zamer (add) and only views it afterwards
OPERATOR_LAVOZIM = "operator"
OPERATOR_NEVER = ("change_metering", "delete_metering", "change_status")
_STEERS = (("oauth", "user_metering"), ("metering", "manage_metering"))


def _is_operator_lavozim(group) -> bool:
    return group is not None and " ".join(group.name.split()).lower() == OPERATOR_LAVOZIM


def _operator_never(perms) -> list:
    return [
        p
        for p in perms
        if not (p.content_type.app_label == "metering" and p.codename in OPERATOR_NEVER)
    ]


def operators_view_meterings_only(users) -> None:
    """Take the zamer editing from these operators' own rights, unless the person also
    steers zamers (zamerchi / bosh menejer) or is an administrator."""
    from django.contrib.auth.models import Permission

    edit = list(
        Permission.objects.filter(
            content_type__app_label="metering", codename__in=OPERATOR_NEVER
        )
    )
    for u in users:
        if u.is_superuser or any(u.has_perm(f"{a}.{c}") for a, c in _STEERS):
            continue
        u.user_permissions.remove(*edit)
        for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            u.__dict__.pop(attr, None)


def merge_group(source, target=None) -> dict:
    """Move every member (and the union of the permissions, so nobody loses a right) of
    `source` into `target`, or — target=None — give the permissions to each member
    personally; then delete `source`."""
    from django.contrib.auth.models import Permission
    from django.db import transaction

    _merge_checks(source, target)
    with transaction.atomic():
        members = list(source.user_set.all())
        perms = list(source.permissions.select_related("content_type"))
        name = source.name
        if _is_operator_lavozim(target):
            perms = _operator_never(perms)  # an old call-centre group must not undo the rule
        if target is not None:
            added = {p for p in perms} - set(target.permissions.all())
            target.permissions.add(*perms)
            target.user_set.add(*members)
        else:
            added = set()
            for u in members:
                have = set(u.user_permissions.all())
                missing = [p for p in perms if p not in have]
                if missing:
                    u.user_permissions.add(*missing)
                    added.update(missing)
        # members get panel access when they end up with any right (source or target)
        if perms or (target is not None and target.permissions.exists()):
            for u in members:
                if not u.is_staff:
                    u.is_staff = True
                    u.save(update_fields=["is_staff"])
        source.delete()
        if _is_operator_lavozim(target):
            operators_view_meterings_only(members)
    for u in members:
        for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            u.__dict__.pop(attr, None)
    keys = sorted(
        f"{p.content_type.app_label}.{p.codename}"
        for p in Permission.objects.filter(pk__in=[p.pk for p in added]).select_related(
            "content_type"
        )
    )
    return {"moved_members": len(members), "added_permissions": keys, "deleted": name}


def merge_all() -> dict:
    """Apply every suggestion of merge_plan() at once: «rename» renames, «merge» moves the
    group into its lavozim, «to_personal» gives its rights to the members; «choose»
    (nothing suggested) is left for the owner. One group failing does not stop the rest.
    Nobody loses a right (merge_group). Repeats while something still happens: a
    rename can give a later group its target."""
    done, skipped = [], {}
    for _ in range(3):
        before = len(done)
        _merge_pass(done, skipped)
        if len(done) == before:
            break
    left = {i["group"]["name"] for i in merge_plan()["items"]}
    return {"done": done, "skipped": [s for n, s in skipped.items() if n in left]}


def _merge_pass(done: list, skipped: dict) -> None:
    from django.contrib.auth.models import Group

    from core.exceptions import ServiceError

    for item in merge_plan()["items"]:
        name = item["group"]["name"]
        group = Group.objects.filter(pk=item["group"]["id"]).first()
        if group is None:
            continue
        try:
            if item["action"] == "rename":
                rename_group(group, item["rename_to"])
                done.append({"group": name, "to": item["rename_to"], "action": "rename"})
            elif item["action"] == "merge":
                target = Group.objects.get(pk=item["suggested"]["id"])
                merge_group(group, target)
                done.append({"group": name, "to": target.name, "action": "merge"})
            elif item["action"] == "to_personal":
                merge_group(group, None)
                done.append({"group": name, "to": None, "action": "to_personal"})
            else:
                skipped[name] = {"group": name, "reason": item["reason"]}
        except (ServiceError, Group.DoesNotExist) as e:
            skipped[name] = {"group": name, "reason": str(getattr(e, "message", e))}


# --- Personal rights: only the lavozim gives rights now -------------------------------

PERSONAL_RIGHTS_OFF = (
    "Huquqlar lavozim orqali beriladi: Xodimlar → Lavozimlar → lavozimni tahrirlang "
    "va xodimni o'sha lavozimga qo'shing."
)


def personal_rights(user) -> list:
    """The rights the person holds directly (from the old per-person switches), as
    section labels. Uses the prefetched user_permissions when there are any."""
    keys = {f"{p.content_type.app_label}.{p.codename}" for p in user.user_permissions.all()}
    return _perm_labels(keys) if keys else []


def clear_personal_rights(user) -> int:
    """Owner's rule: rights come from the lavozim only — drop the person's own ones.
    What the person needs must be on their lavozim (shown before clearing)."""
    from core.exceptions import ServiceError

    if user.is_superuser:
        raise ServiceError("Administrator hamma bo'limni ko'radi — shaxsiy huquq yo'q")
    n = user.user_permissions.count()
    user.user_permissions.clear()
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    return n

