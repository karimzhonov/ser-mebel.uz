"""FSM of the painter's «✅ Bajardim» flow (default destiny on purpose, like `RoverDone`: while
it is open the HR `PendingAnswer` filter stays quiet and the other flows see a busy state).
Context in the FSM data (Redis, shared by the workers): pid, chat_id, message_id (the task
card), url, ts (30 min TTL, refreshed on every step), note."""

from aiogram.fsm.state import State, StatesGroup


class PainterDone(StatesGroup):
    note = State()
    confirm = State()
