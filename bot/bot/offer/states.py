"""FSM of the typed answers. Default destiny on purpose (like crm `TaskDone`, metering
`Meter*`): while one is open the HR `PendingAnswer` filter stays quiet and the other flows
see a busy state. The context (k, oid, chat_id, message_id, card kind, ts for the 10 min
TTL) is in the FSM data (Redis, shared by the uvicorn workers, survives restarts)."""

from aiogram.fsm.state import State, StatesGroup


class OfferDue(StatesGroup):
    """A typed new deadline of a design / price."""

    custom = State()


class OfferAnswer(StatesGroup):
    """The manager's typed comment (changes / recalc) or reason (declined)."""

    comment = State()
    reason = State()
