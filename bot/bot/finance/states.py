"""FSM states of the finance bot. The draft itself (keys `t`, `kind`, `uid`, `amount`,
`step`, ...) lives in the FSM data, like the old `BotSession.data`; `d["step"]` names the
current step and `STEP_STATE` maps it to the aiogram state."""

from aiogram.fsm.state import State, StatesGroup


class Tx(StatesGroup):
    amount = State()
    rate = State()
    category = State()
    worker = State()
    paytype = State()
    car = State()
    order = State()
    ord_text = State()
    comment = State()
    receipt = State()
    confirm = State()


class Attach(StatesGroup):
    receipt = State()


class Request(StatesGroup):
    amount = State()
    reason = State()
    custom = State()


class Transfer(StatesGroup):
    amount = State()
    comment = State()
    confirm = State()


class ManualOrder(StatesGroup):
    ref = State()
    client = State()
    phone = State()
    price = State()
    newprice = State()


class MonthReport(StatesGroup):
    confirm = State()
    note = State()


class BonusPay(StatesGroup):
    amount = State()


class AdvanceSum(StatesGroup):
    amount = State()


class Feedback(StatesGroup):
    photo = State()


class Template(StatesGroup):
    photo = State()


class Debt(StatesGroup):
    creditor = State()
    item = State()
    amount = State()
    category = State()
    order = State()
    ord_text = State()
    confirm = State()
    pay_amount = State()
    pay_confirm = State()


# step name (the old BotSession.data["step"]) -> state
STEP_STATE = {
    "amount": Tx.amount,
    "rate": Tx.rate,
    "category": Tx.category,
    "worker": Tx.worker,
    "paytype": Tx.paytype,
    "car": Tx.car,
    "order": Tx.order,
    "ord_text": Tx.ord_text,
    "comment": Tx.comment,
    "receipt": Tx.receipt,
    "confirm": Tx.confirm,
    "attach": Attach.receipt,
    "req_amount": Request.amount,
    "req_reason": Request.reason,
    "req_custom": Request.custom,
    "tr_amount": Transfer.amount,
    "tr_com": Transfer.comment,
    "tr_confirm": Transfer.confirm,
    "o_id": ManualOrder.ref,
    "o_client": ManualOrder.client,
    "o_phone": ManualOrder.phone,
    "o_price": ManualOrder.price,
    "o_newprice": ManualOrder.newprice,
    "month_confirm": MonthReport.confirm,
    "month_note": MonthReport.note,
    "bpay": BonusPay.amount,
    "adv_sum": AdvanceSum.amount,
    "fikr": Feedback.photo,
    "tpl": Template.photo,
    "qz_from": Debt.creditor,
    "qz_item": Debt.item,
    "qz_amount": Debt.amount,
    "qz_cat": Debt.category,
    "qz_order": Debt.order,
    "qz_ord_text": Debt.ord_text,
    "qz_confirm": Debt.confirm,
    "qz_pay_amount": Debt.pay_amount,
    "qz_pay_confirm": Debt.pay_confirm,
}

ALL_STATES = [
    s
    for grp in (
        Tx,
        Attach,
        Request,
        Transfer,
        ManualOrder,
        MonthReport,
        BonusPay,
        AdvanceSum,
        Feedback,
        Template,
        Debt,
    )
    for s in grp.__all_states__
]
