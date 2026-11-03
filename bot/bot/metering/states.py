"""FSM of the measurer's typed answers. Default destiny on purpose (like crm `TaskDone`):
while one is open the HR `PendingAnswer` filter stays quiet and the other flows see a busy
state. The context (metering, chat_id, message_id, kind, ts for the 10 min TTL) is in the
FSM data (Redis, shared by the uvicorn workers, survives restarts)."""

from aiogram.fsm.state import State, StatesGroup


class MeterTime(StatesGroup):
    """A typed new date / time of a zamer."""

    custom = State()


class MeterCancel(StatesGroup):
    """A typed reason of a cancelled zamer."""

    reason = State()
