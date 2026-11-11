"""FSM of the worker's «✅ Bajardim» flow (default destiny on purpose, like `OfferDue`: while it
is open the HR `PendingAnswer` filter stays quiet and the other flows see a busy state).
Context in the FSM data (Redis, shared by the workers): rid, chat_id, message_id (the task
card), url, ts (30 min TTL, refreshed on every step), amount, note."""

from aiogram.fsm.state import State, StatesGroup


class RoverDone(StatesGroup):
    amount = State()
    note = State()
    confirm = State()
