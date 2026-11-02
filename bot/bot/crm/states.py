"""FSM of the «Yangi mijoz» lead form.

Default destiny on purpose: while a lead is being filled, the HR `PendingAnswer` filter
(which only acts on an empty default-destiny state) stays quiet, and the crm entry filter
refuses to start over a finance draft (any non-`Lead:*` state). The draft lives in the FSM
data (Redis: shared by the uvicorn workers, survives restarts, 6 h TTL).
"""

from aiogram.fsm.state import State, StatesGroup


class Lead(StatesGroup):
    name = State()
    phone = State()
    source = State()
    note = State()
    remind = State()
    remind_custom = State()
    confirm = State()
    saving = State()
