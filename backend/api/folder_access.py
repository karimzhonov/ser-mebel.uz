"""Who may open a Filer folder through the API.

Every Замер / Дизайн / Расчёт / Заказ / production row owns a folder
(core/utils/filer.py). Staff rarely hold the generic `filer.*` permissions, so the
folder buttons on those pages used to 403 for everyone but superusers. Here access
follows the object instead: if you may see the object (same permission and the same
row scoping as its list page), you may open its folder and everything below it.

Order folders also hold the metering, detailing, assembly … sub-folders, so a folder
is reachable through any object whose folder is the folder itself or one of its
ancestors.

Owner's rule (intentional): production staff (detailing / rover / painter / assembly)
open the whole folder of their order — the measurements and design files are what
they build from — except "Расчёт цены", which needs a price permission.
"""

from django.db.models import Q

from metering.design.models import DesignType
from metering.models import Metering
from metering.price.models import Price
from order.assembly.constants import ASSEMBLY_MANAGER_PERMISSION
from order.assembly.models import Assembly
from order.detailing.models import Detailing
from order.models import Order
from order.painter.models import Painter
from order.painter.services import ready_for_painter
from order.rover.models import Rover


def _chain(folder, limit=20):
    ids = []
    node = folder
    while node is not None and len(ids) < limit:
        ids.append(node.pk)
        node = node.parent
    return ids


def _owned(user, ids):
    """Querysets of objects the user may see whose folder is in `ids`."""
    manager = user.has_perm(f"assembly.{ASSEMBLY_MANAGER_PERMISSION}")
    in_chain = Q(folder_id__in=ids)
    order_in_chain = Q(order__folder_id__in=ids)

    if user.has_perm("metering.view_metering"):
        yield Metering.objects.filter(in_chain)
    if user.has_perm("design.view_design"):
        # Designers work from the metering's files ("Файлы замера") and their variants,
        # plus the "Дизайн" folder that holds the variants (breadcrumb "up").
        yield DesignType.objects.filter(in_chain | Q(folder__parent_id__in=ids))
        yield Metering.objects.filter(in_chain, design__isnull=False)
    if user.has_perm("price.view_price"):
        yield Price.objects.filter(in_chain)
        yield Metering.objects.filter(in_chain, price__isnull=False)
    if user.has_perm("order.view_order"):
        yield Order.objects.filter(in_chain)
    if user.has_perm("detailing.view_detailing"):
        yield Detailing.objects.filter(in_chain | order_in_chain)
    if user.has_perm("rover.view_rover"):
        yield Rover.objects.filter(in_chain | order_in_chain)
    if user.has_perm("painter.view_painter"):
        painters = ready_for_painter(Painter.objects.filter(in_chain | order_in_chain))
        if not manager:
            painters = painters.filter(type__user=user)
        yield painters
    if user.has_perm("assembly.view_assembly"):
        assemblies = Assembly.objects.filter(in_chain | order_in_chain)
        if not manager:
            assemblies = assemblies.filter(user=user)
        yield assemblies


def _price_files_hidden(user, ids) -> bool:
    """ "Расчёт цены" lives inside the order folder that production staff may open;
    its files carry money, so they stay closed without the price permissions."""
    if user.has_perm("price.view_price") or user.has_perm("order.view_order_price"):
        return False
    return Price.objects.filter(folder_id__in=ids).exists()


def works_on_folder(user, folder) -> bool:
    """The user may see an object that owns this folder (or one of its parents)."""
    if user.is_superuser:
        return True
    ids = _chain(folder)
    if _price_files_hidden(user, ids):
        return False
    return any(qs.exists() for qs in _owned(user, ids))


def folder_rights(user, folder) -> dict:
    """What the user may do in this folder. Working on the owning object grants
    view + upload + sub-folders + discussion; the generic filer.* permissions still
    work as before. Deleting someone else's file always needs filer.delete_file."""
    works = works_on_folder(user, folder)
    view = works or user.has_perm("filer.view_folder")
    return {
        "view": view,
        "upload": view and (works or user.has_perm("filer.add_file")),
        # Never granted by working on an object: folder names drive the automatic
        # folder layout (see core/utils/filer.py), so creating them stays with filer.*.
        "create_folder": view and user.has_perm("filer.add_folder"),
        "comment": view and (works or user.has_perm("discussion.add_discussionmessage")),
        "delete_any": user.has_perm("filer.delete_file"),
    }
