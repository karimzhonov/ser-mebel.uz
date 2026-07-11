from django.db import transaction
from filer.models.foldermodels import Folder

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
    )

    created_history = price.history.order_by("history_date").first()
    created_user = created_history.history_user if created_history else None

    with transaction.atomic():
        price_folder, _ = Folder.objects.get_or_create(
            name="Расчёт цены", parent=price.metering.folder, defaults={"owner": created_user}
        )
        price.folder = price_folder
        price.save(update_fields=["folder"])
