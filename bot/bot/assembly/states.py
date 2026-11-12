"""FSM of the assembler's «✅ O'rnatildi» flow (default destiny on purpose, like
`PainterDone`: while it is open the HR `PendingAnswer` filter stays quiet and the other flows
see a busy state). Context in the FSM data (Redis, shared by the workers): aid, chat_id,
message_id (the task card), url, ts (30 min TTL, refreshed on every step), note."""

from aiogram.fsm.state import State, StatesGroup


class AssemblyFinish(StatesGroup):
    note = State()
    confirm = State()
