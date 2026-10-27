"""DTOs of the internal bot API (docs/BOT_CONTRACT.md, section 1.2).

The builders live next to the data (accounting/dto.py, hr/services.py) because the
event payloads (accounting/events.py, hr/events.py) use the very same shapes; this
module is the one place the bot views import them from.
"""

from accounting.dto import (  # noqa: F401
    bonus_dto,
    car_dto,
    category_dto,
    day_summary_dto,
    dec,
    feedback_dto,
    iso,
    manual_order_dto,
    member_dto,
    money_state_dto,
    month_summary_dto,
    operation_dto,
    operation_row_dto,
    order_brief_dto,
    order_card_dto,
    request_dto,
    task_dto,
    warranty_dto,
    worker_dto,
)
from hr.services import employee_dto, group_dto  # noqa: F401
