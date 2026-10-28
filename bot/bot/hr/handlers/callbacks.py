"""`dv:` inline buttons of the davomat bot.

Employee buttons (uni, lr, er, eta, here, cant, rsn, offreq) go to `hr/callback/`; the
backend decides and says what to answer. Manager buttons (menus, off days, working hours,
holiday question, winner pick, off-day request, reset) call the same endpoints as the
commands. Callback data strings are the old ones, so buttons in old chats keep working.
"""

from __future__ import annotations

import logging
from datetime import date

from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api
from .. import keyboards as K
from .. import messages as M
from ..fmt import days_label, esc, fmt_day
from ..states import HolidayDays, hr_context
from ..texts import IV_TITLE, WD_SHORT
from .admin import (
    DECIDED,
    active_employees,
    decide_holiday,
    emp_path,
    notify_employee,
    run_admin_command,
)
from .employee import private_router

log = logging.getLogger("bot.hr.callbacks")

ADMIN_KINDS = {"dk", "dkt", "dkd", "offok", "offno", "dkp", "hol", "m", "iv", "ivs", "ivp", "ann", "rst"}
MENU_COMMANDS = {
    "today": "dhisobot",
    "month": "doy",
    "emps": "dxodimlar",
    "hol": "bayramlar",
    "set": "dsozlamalar",
    "sheet": "djadval",
    "help": "dyordam",
    "rank": "reyting",
}
OFF_TITLE = "Kimning dam kunlarini belgilaymiz?"


def _message(cb: CallbackQuery) -> Message | None:
    return cb.message if isinstance(cb.message, Message) else None


@private_router.callback_query(F.data.startswith("dv:"))
@api.guarded
async def on_dv_callback(cb: CallbackQuery, state: FSMContext, actor=None):
    actor = await api.ensure_actor(actor, cb.from_user)
    p = (cb.data or "")[3:].split(":")
    if p[0] in ADMIN_KINDS:
        if not api.is_admin(actor):
            await cb.answer("Faqat rahbar uchun")
            return
        await _admin_callback(cb, p, state)
        return
    await _employee_callback(cb, p, actor)


# ------------------------------------------------------------------ employee buttons
async def _employee_callback(cb: CallbackQuery, p: list[str], actor: dict) -> None:
    if not api.employee_of(actor):
        await cb.answer("Siz ro'yxatda yo'qsiz")
        return
    action = p[0]
    day = p[1] if len(p) > 1 else ""
    arg = p[2] if len(p) > 2 else ""
    res = await api.call(
        "POST",
        "hr/callback/",
        actor=cb.from_user.id,
        json={"action": action, "day": day, "arg": arg},
    )
    await cb.answer(res.get("answer") or None, show_alert=bool(res.get("alert")))
    msg = _message(cb)
    if res.get("clear_kb"):
        await api.clear_kb(msg)
    reply = res.get("reply")
    if reply:
        text, kb = M.callback_reply(reply["kind"], reply.get("data") or {}, day)
        if msg:
            await api.answer(msg, text, kb)
        else:
            await api.send(cb.from_user.id, text, kb)


# ------------------------------------------------------------------ manager buttons
async def _admin_callback(cb: CallbackQuery, p: list[str], state: FSMContext) -> None:
    uid = cb.from_user.id
    msg = _message(cb)
    kind = p[0]

    async def edit(text: str, kb=None) -> None:
        await api.edit(msg, text, kb)

    async def say(text: str, kb=None) -> None:
        if msg:
            await api.answer(msg, text, kb)
        else:
            await api.send(uid, text, kb)

    if kind == "m":
        await cb.answer()
        if p[1] == "off":
            return await edit(OFF_TITLE, K.emp_picker_kb(await active_employees(uid), 0))
        if p[1] == "iv":
            return await edit(IV_TITLE, K.emp_picker_kb(await active_employees(uid), 0, "iv"))
        cmd = MENU_COMMANDS.get(p[1])
        if cmd:
            await run_admin_command(cmd, [], uid, say)
        return
    if kind == "hol":
        return await _holiday(cb, p, state, edit)
    if kind == "dkp":
        await cb.answer()
        return await edit(OFF_TITLE, K.emp_picker_kb(await active_employees(uid), int(p[1])))
    if kind == "rst":
        await cb.answer()
        if p[1] == "no":
            return await edit("Bekor qilindi. Hech narsa o'chirilmadi.")
        d = date.fromisoformat(p[1])
        await api.call("POST", "hr/reset/", actor=uid, json={"since": d.isoformat()})
        return await edit(
            f"✅ Tozalandi. Hisob <b>{fmt_day(d)}</b> dan boshlanadi.\n"
            "Keldi-ketdi, ballar va reyting shu kundan yangidan yoziladi."
        )
    if kind == "ivp":
        await cb.answer()
        return await edit(IV_TITLE, K.emp_picker_kb(await active_employees(uid), int(p[1]), "iv"))
    if kind == "ann":
        await cb.answer()
        return await _announce(cb, p, edit)
    if kind in ("iv", "ivs"):
        return await _hours(cb, p, edit)
    if kind in ("offok", "offno"):
        return await _off_request(cb, p, edit)
    # dk / dkt / dkd: one employee's off days
    return await _off_days(cb, p, edit)


async def _get_emp(cb: CallbackQuery, ref: str) -> dict | None:
    try:
        return await api.call("GET", emp_path(ref), actor=cb.from_user.id)
    except api.NotFound:
        await cb.answer("Xodim topilmadi")
        return None


async def _holiday(cb: CallbackQuery, p: list[str], state: FSMContext, edit) -> None:
    uid = cb.from_user.id
    hol_day = date.fromisoformat(p[1])
    await cb.answer()
    dec = await api.call("GET", f"hr/holidays/{hol_day.isoformat()}/decision/", actor=uid)
    if dec.get("decided"):
        return await edit(DECIDED)
    name = dec.get("name") or ""
    if p[2] == "x":
        hr = hr_context(state)
        await hr.set_state(HolidayDays.days)
        await hr.update_data(hol_day=hol_day.isoformat())
        return await edit(
            f"🎉 {fmt_day(hol_day)} — {esc(name)}.\nNecha kun dam olinadi? Son yozing. "
            "Boshqa sanadan boshlansa, sanasini ham yozing, masalan: <code>3 20.03</code>"
        )
    n = int(p[2])
    await edit(f"🎉 {fmt_day(hol_day)} — {esc(name)}: " + (f"{n} kun dam." if n else "ishlaymiz."))
    try:
        await decide_holiday(uid, hol_day, n, hol_day)
    except api.Conflict:
        await edit(DECIDED)


async def _announce(cb: CallbackQuery, p: list[str], edit) -> None:
    uid = cb.from_user.id
    kind, period, tg = p[1], p[2], int(p[3])
    try:
        e = await api.call("GET", emp_path(str(tg)), actor=uid)
    except api.NotFound:
        return await edit("Xodim topilmadi.")
    try:
        res = await api.call(
            "POST",
            "hr/winners/",
            actor=uid,
            json={"kind": kind, "period": period, "employee_tg": tg},
        )
    except api.Conflict:
        return await edit("Bu tanlov allaqachon e'lon qilingan.")
    except api.NotFound:
        return await edit("Xodim topilmadi.")
    await edit(
        f"✅ {esc(e['name'])} — {'oy' if kind == 'm' else 'yil'} xodimi sifatida "
        f"{res['groups_count']} ta guruhda e'lon qilindi."
    )


async def _hours(cb: CallbackQuery, p: list[str], edit) -> None:
    uid = cb.from_user.id
    ee = await _get_emp(cb, p[1])
    if not ee:
        return
    if p[0] == "iv":
        await cb.answer()
        settings = {
            s["key"]: s["value"] for s in await api.call("GET", "hr/settings/", actor=uid) or []
        }
        general = (settings.get("WORK_START", "09:00"), settings.get("WORK_END", "18:00"))
        return await edit(
            f"🕐 <b>{esc(ee['name'])}</b> ish vaqti (hozir {ee['hours_label']}):",
            K.iv_kb(ee, general),
        )
    if p[2] == "0":
        body = {"reset_hours": True}
    else:
        t1, t2 = p[2].split("-")
        body = {"work_start": f"{t1[:2]}:{t1[2:]}", "work_end": f"{t2[:2]}:{t2[2:]}"}
    ee = await api.call("PATCH", emp_path(p[1]), actor=uid, json=body)
    await notify_employee(uid, p[1], "hours")
    await cb.answer("Saqlandi")
    await edit(
        f"✅ <b>{esc(ee['name'])}</b>: {ee['hours_label']}\n\n{IV_TITLE}",
        K.emp_picker_kb(await active_employees(uid), 0, "iv"),
    )


async def _off_request(cb: CallbackQuery, p: list[str], edit) -> None:
    uid = cb.from_user.id
    day = date.fromisoformat(p[1])
    e = await _get_emp(cb, p[2])
    if not e:
        return
    await cb.answer()
    approve = p[0] == "offok"
    # the backend emits hr.off_request_answered: the employee is told there
    await api.call(
        "POST",
        "hr/off-requests/",
        actor=uid,
        json={"employee_tg": e["telegram_id"], "day": day.isoformat(), "approve": approve},
    )
    if approve:
        await edit(f"✅ {esc(e['name'])}: {fmt_day(day)} dam kuni deb tasdiqlandi.")
    else:
        await edit(f"❌ {esc(e['name'])}: dam kuni rad etildi.")


async def _off_days(cb: CallbackQuery, p: list[str], edit) -> None:
    uid = cb.from_user.id
    kind = p[0]
    e = await _get_emp(cb, p[1])
    if not e:
        return
    title = f"<b>{esc(e['name'])}</b> dam kunlarini belgilang (bir nechta tanlash mumkin):"
    if kind == "dk":
        await cb.answer()
        return await edit(title, K.off_days_kb(e))
    if kind == "dkt":
        d = int(p[2])
        e = await api.call("PATCH", emp_path(p[1]), actor=uid, json={"toggle_off_day": d})
        was_set = d in (e.get("off_days") or [])
        await cb.answer(WD_SHORT[d - 1] + (" qo'shildi" if was_set else " olib tashlandi"))
        return await edit(title, K.off_days_kb(e))
    if kind == "dkd":
        await cb.answer("Saqlandi")
        await notify_employee(uid, p[1], "off_days")
        return await edit(
            f"✅ <b>{esc(e['name'])}</b> dam kunlari: {days_label(e.get('off_days') or [])}",
            K.emp_picker_kb(await active_employees(uid), 0),
        )
