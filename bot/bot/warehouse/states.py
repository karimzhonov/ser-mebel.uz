"""FSM of the omborchi (warehouse keeper) flows. Default destiny on purpose (like metering /
offer): while one is open the other flows see a busy state. The context (pid, draft, ts for
the 30 min staleness check) is in the FSM data (Redis, shared by the uvicorn workers)."""

from aiogram.fsm.state import State, StatesGroup


class WhSearch(StatesGroup):
    query = State()


class WhIn(StatesGroup):
    """Kirim: quantity -> price -> supplier -> confirm."""

    qty = State()
    price = State()
    party = State()
    confirm = State()


class WhOut(StatesGroup):
    """Chiqim: client IDs (toggles / typed) -> quantity per ID (or one quantity without
    clients) -> receiver -> confirm."""

    refs = State()
    alloc = State()
    qty = State()
    party = State()
    confirm = State()


class WhNew(StatesGroup):
    """Yangi mahsulot."""

    name = State()
    unit = State()
    category = State()
    code = State()
    min_qty = State()


class WhEdit(StatesGroup):
    value = State()


class WhPhoto(StatesGroup):
    wait = State()


ALL = (WhSearch, WhIn, WhOut, WhNew, WhEdit, WhPhoto)
