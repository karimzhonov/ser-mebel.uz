"""Manager commands of the davomat bot (private chat). A manager is a finance admin: the
backend says so in `actor["hr"]["is_admin"]` and enforces it again on every endpoint.

Every command maps its arguments to one or two `hr/...` endpoints; the backend validates
and emits the DMs (hr.* events), the handler only answers the manager.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from datetime import date, timedelta

from aiogram import F
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.common import fmt as common_fmt

from .. import api
from .. import keyboards as K
from .. import reports as R
from ..fmt import (
    days_label,
    esc,
    fmt_day,
    hm_str,
    last_day_of_month,
    month_name,
    parse_date,
    parse_days,
    parse_hm,
)
from ..links import site_url
from ..states import HolidayDays, hr_context
from ..texts import (
    ADMIN_CMDS,
    ADMIN_HELP,
    FINANCE_MENU_BUTTONS,
    IV_TITLE,
    MENU_BTN,
    SETTING_KEYS,
    WD_SHORT,
)
from .employee import private_router

log = logging.getLogger("bot.hr.admin")

Reply = Callable[..., Awaitable]
YM = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
DECIDED = "Bu bayram bo'yicha qaror allaqachon qabul qilingan."


# ------------------------------------------------------------------ filters
class HrAdmin(BaseFilter):
    """Passes only for managers (`actor["hr"]["is_admin"]`)."""

    async def __call__(self, event, actor=None):
        if actor is None:
            try:
                actor = await api.ensure_actor(None, event.from_user)
            except api.BackendError:
                return False
        return {"actor": actor} if api.is_admin(actor) else False


class HolidayAnswer(BaseFilter):
    """Text typed after «✏️ Boshqa (yozaman)» on a holiday question (HR-destiny FSM state).
    Yields only while no finance flow is open."""

    async def __call__(self, message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text or text.startswith("/") or text in FINANCE_MENU_BUTTONS:
            return False
        if await state.get_state() is not None:
            return False
        hr = hr_context(state)
        if await hr.get_state() != HolidayDays.days.state:
            return False
        return {"hr_state": hr}


# ------------------------------------------------------------------ handlers
@private_router.message(Command(*ADMIN_CMDS), HrAdmin())
@api.guarded
async def on_admin_command(message: Message, command: CommandObject):
    a = (command.args or "").split()
    await run_admin_command(
        command.command.lower(), a, message.from_user.id, lambda t, k=None: api.answer(message, t, k)
    )


@private_router.message(F.text == MENU_BTN, HrAdmin())
@api.guarded
async def on_menu_button(message: Message):
    await admin_menu(lambda t, k=None: api.answer(message, t, k))


@private_router.message(F.text, HolidayAnswer())
@api.guarded
async def on_holiday_days(message: Message, hr_state: FSMContext):
    data = await hr_state.get_data()
    await hr_state.clear()
    text = (message.text or "").strip()
    mm = re.fullmatch(r"(\d{1,2})(?:\s+(\S+))?", text)
    if not mm or not data.get("hol_day"):
        raise SkipHandler  # not a number: whatever it is, finance may want it
    hol_day = date.fromisoformat(data["hol_day"])
    start = parse_date(mm[2], common_fmt.today()) if mm[2] else hol_day
    try:
        await decide_holiday(message.from_user.id, hol_day, int(mm[1]), start or hol_day)
    except api.Conflict:
        await message.answer(DECIDED)


async def decide_holiday(uid: int, hol_day: date, n: int, start: date) -> dict:
    """The answer to «dam olinadimi?». The backend emits hr.holiday_applied, which tells the
    managers and the groups (hr/notify.py)."""
    return await api.call(
        "POST",
        f"hr/holidays/{hol_day.isoformat()}/decision/",
        actor=uid,
        json={"n": n, "start": start.isoformat()},
    )


# ------------------------------------------------------------------ the commands
async def admin_menu(reply: Reply) -> None:
    await reply("🕘 <b>Davomat</b>\nNimani ko'rasiz?", K.admin_menu_kb())


async def active_employees(uid: int) -> list[dict]:
    return await api.call("GET", "hr/employees/", actor=uid, params={"active": "1"}) or []


def emp_path(ref: str) -> str:
    return f"hr/employees/{ref}/"


async def run_admin_command(cmd: str, a: list[str], uid: int, reply: Reply) -> None:
    today = common_fmt.today()

    async def need_emp() -> dict | None:
        if not a:
            await reply("Xodim raqamini yozing (masalan 5). Ro'yxat: /dxodimlar")
            return None
        try:
            return await api.call("GET", emp_path(a[0]), actor=uid)
        except api.NotFound:
            await reply(f"Xodim topilmadi: {esc(a[0])}. Ro'yxat: /dxodimlar")
            return None

    if cmd == "dyordam":
        return await reply(ADMIN_HELP)
    if cmd == "davomat":
        return await admin_menu(reply)
    if cmd == "dhisobot":
        d = parse_date(a[0], today) if a else today
        if not d:
            return await reply("Sana noto'g'ri. Masalan: /dhisobot 20.10.2026")
        r = await api.call(
            "GET", "hr/reports/day/", actor=uid, params={"date": d.isoformat()}
        )
        return await reply(R.render_day(r, "📊 Bugungi hisobot"))
    if cmd == "dkecha":
        r = await api.call(
            "GET",
            "hr/reports/day/",
            actor=uid,
            params={"date": (today - timedelta(days=1)).isoformat()},
        )
        return await reply(R.render_day(r, "📊 Hisobot"))
    if cmd == "dhafta":
        start = today - timedelta(days=today.isoweekday() - 1)
        return await reply(await _period(uid, start, today, "📅 Haftalik hisobot"))
    if cmd == "doy":
        ym = a[0] if a and YM.fullmatch(a[0]) else today.strftime("%Y-%m")
        return await reply(
            await _period(
                uid,
                date.fromisoformat(ym + "-01"),
                last_day_of_month(ym),
                f"🗓 Oylik hisobot ({ym})",
            )
        )
    if cmd == "djadval":
        return await reply(f"🌐 Davomat jurnali va reyting saytda: {site_url()}")
    if cmd == "dxodimlar":
        return await reply(await _employees_text(uid))
    if cmd == "damkun":
        if len(a) >= 2:
            e = await need_emp()
            if not e:
                return
            body = {"off_days": "general" if a[1].lower() == "umumiy" else a[1]}
            e = await api.call("PATCH", emp_path(a[0]), actor=uid, json=body)
            return await reply(
                f"✅ {esc(e['name'])} dam kunlari: {days_label(e['off_days_effective'])}"
            )
        return await reply(
            "Kimning dam kunlarini belgilaymiz?", K.emp_picker_kb(await active_employees(uid), 0)
        )
    if cmd == "dam":
        e = await need_emp()
        if not e:
            return
        d = parse_date(a[1] if len(a) > 1 else "bugun", today)
        if not d:
            return await reply("Format: /dam 5 bugun yoki /dam 5 25.10.2026")
        await api.call(
            "POST", "hr/day-off/", actor=uid, json={"employee": a[0], "date": d.isoformat()}
        )
        return await reply(f"✅ {esc(e['name'])}: {fmt_day(d)} dam kuni.")
    if cmd == "tatil":
        if len(a) < 2:
            return await reply(
                "Format: /tatil 5 25.10.2026 30.10.2026 sabab\n(bir kunlik: /tatil 5 bugun kasal)"
            )
        e = await need_emp()
        if not e:
            return
        d_from = parse_date(a[1], today)
        if not d_from:
            return await reply(f"Sana noto'g'ri: {esc(a[1])}")
        d_to, rest = d_from, a[2:]
        if rest and parse_date(rest[0], today):
            d_to, rest = parse_date(rest[0], today), rest[1:]
        reason = " ".join(rest) or "ta'til"
        lv = await api.call(
            "POST",
            "hr/leaves/",
            actor=uid,
            json={
                "employee": a[0],
                "date_from": d_from.isoformat(),
                "date_to": d_to.isoformat(),
                "reason": reason,
            },
        )
        return await reply(
            f"✅ {esc(e['name'])}: {lv['date_from']} — {lv['date_to']} ({esc(reason)}), "
            f"#{lv['number']}"
        )
    if cmd == "tatillar":
        lv = await api.call("GET", "hr/leaves/", actor=uid) or []
        if not lv:
            return await reply("Faol ta'tillar yo'q.")
        return await reply(
            "<b>🏖 Ta'tillar</b>\n"
            + "\n".join(
                f"#{x['number']} {esc(x['employee']['name'])}: {x['date_from']} — "
                f"{x['date_to']} ({esc(x['reason'])})"
                for x in lv
            )
        )
    if cmd == "tatil_ochir":
        n = re.sub(r"\D", "", a[0]) if a else ""
        if not n:
            return await reply("Topilmadi.")
        try:
            await api.call("DELETE", f"hr/leaves/{int(n)}/", actor=uid)
        except api.NotFound:
            return await reply("Topilmadi.")
        return await reply("✅ O'chirildi.")
    if cmd == "bayram":
        d = parse_date(a[0], today) if a else None
        if not d:
            return await reply("Format: /bayram 01.01.2027 Yangi yil")
        name = " ".join(a[1:]) or "bayram"
        await api.call(
            "POST", "hr/holidays/", actor=uid, json={"day": d.isoformat(), "name": name[:128]}
        )
        return await reply(f"🎉 {d} — {esc(name)} dam kuni sifatida belgilandi.")
    if cmd == "bayramlar":
        hs = await api.call("GET", "hr/holidays/", actor=uid) or []
        return await reply(
            "<b>🎉 Bayramlar</b>\n"
            + ("\n".join(f"{h['day']} — {esc(h['name'])}" for h in hs) or "Yo'q")
        )
    if cmd == "bayram_ochir":
        d = parse_date(a[0], today) if a else None
        if not d:
            return await reply("Topilmadi.")
        try:
            await api.call("DELETE", f"hr/holidays/{d.isoformat()}/", actor=uid)
        except api.NotFound:
            return await reply("Topilmadi.")
        return await reply("✅ O'chirildi.")
    if cmd in ("dchiqar", "dqayta"):
        e = await need_emp()
        if not e:
            return
        e = await api.call(
            "PATCH", emp_path(a[0]), actor=uid, json={"is_active": cmd == "dqayta"}
        )
        return await reply(
            f"✅ {esc(e['name'])}"
            + (
                " qayta faollashtirildi."
                if e["is_active"]
                else " ro'yxatdan chiqarildi (tarix saqlanadi)."
            )
        )
    if cmd == "dsozlamalar":
        L = ["<b>⚙️ Sozlamalar</b>", ""]
        for s in await api.call("GET", "hr/settings/", actor=uid) or []:
            v = s["value"]
            if s["key"] == "OFF_DAYS":
                v = days_label(parse_days(v)) if parse_days(v) else "yo'q (har xodimning o'zi)"
            L.append(f"• {s['label']}: <b>{esc(v)}</b>  <code>{s['key']}</code>")
        L += ["", "O'zgartirish: <code>/dsozla REPORT_TIME 11:30</code>"]
        return await reply("\n".join(L))
    if cmd in ("vaqt", "kechikish", "dsozla"):
        return await _setting(cmd, a, uid, reply)
    if cmd == "guruhlar":
        gs = [g for g in await api.call("GET", "hr/groups/", actor=uid) or [] if g["is_active"]]
        return await reply(
            f"<b>🏢 Kuzatilayotgan guruhlar ({len(gs)})</b>\n"
            + (
                "\n".join(f"• {esc(g['title'])}" for g in gs)
                or "Yo'q. Botni guruhga qo'shib, o'sha yerda /ulash yozing."
            )
        )
    if cmd == "dtozala":
        tm = today + timedelta(days=1)
        return await reply(
            "⚠️ <b>Hisobni noldan boshlash</b>\n\nHamma keldi-ketdi yozuvlari, ballar va "
            "qo'shimcha ballar o'chiriladi. Xodimlar ro'yxati, ish vaqtlari, dam kunlari, "
            "bayramlar va sozlamalar saqlanib qoladi.\n\nHisob qachondan boshlansin?",
            K.reset_kb(today, tm),
        )
    if cmd == "ishvaqti":
        return await _work_hours(a, uid, reply, need_emp)
    if cmd == "ball":
        return await _points(a, uid, reply, need_emp)
    if cmd == "reyting":
        if a and re.fullmatch(r"yil|\d{4}", a[0], re.I):
            y = a[0] if a[0].isdigit() else str(today.year)
            rows = await api.call("GET", "hr/ranking/", actor=uid, params={"year": y})
            return await reply(R.year_report(y, rows or []))
        ym = a[0] if a and YM.fullmatch(a[0]) else today.strftime("%Y-%m")
        rows = await api.call("GET", "hr/ranking/", actor=uid, params={"month": ym})
        return await reply(R.ranking_text(rows or [], f"🏆 Reyting — {month_name(ym)}"))
    return await reply("Noma'lum buyruq. /dyordam")


# ------------------------------------------------------------------ pieces
async def _period(uid: int, start: date, end: date, title: str) -> str:
    r = await api.call(
        "GET",
        "hr/reports/period/",
        actor=uid,
        params={"from": start.isoformat(), "to": end.isoformat()},
    )
    return R.period_report(r, title)


async def _employees_text(uid: int) -> str:
    emps = await api.call("GET", "hr/employees/", actor=uid) or []
    if not emps:
        return "Hali xodim yo'q. Xodimlar guruhga yozishi bilan avtomatik qo'shiladi."
    groups = await api.call("GET", "hr/groups/", actor=uid) or []
    multi = len([g for g in groups if g.get("is_active", True)]) > 1
    L = [f"<b>👥 Xodimlar ({sum(1 for e in emps if e['is_active'])} faol)</b>", ""]
    no_off = 0
    for e in emps:
        f = [f"🕐 {e['hours_label']}"]
        if not e["is_active"]:
            f.append("❌ faol emas")
        if e["can_dm"] is False:
            f.append("⚠️ botga ulanmagan")
        off = e["off_days_effective"]
        if off:
            f.append("dam: " + ",".join(WD_SHORT[d - 1] for d in off))
        elif e["is_active"]:
            f.append("dam kuni belgilanmagan")
            no_off += 1
        if multi and e.get("group"):
            f.append(esc(e["group"]["title"]))
        L.append(
            f"#{e['number']} {esc(e['name'])}"
            + (f" @{esc(e['username'])}" if e.get("username") else "")
            + " — "
            + ", ".join(f)
        )
    if no_off:
        L += ["", "💡 Dam kunlarini /damkun orqali belgilang."]
    return "\n".join(L)


async def _setting(cmd: str, a: list[str], uid: int, reply: Reply) -> None:
    async def current(key: str) -> str:
        for s in await api.call("GET", "hr/settings/", actor=uid) or []:
            if s["key"] == key:
                return s["value"]
        return ""

    if cmd == "vaqt" and not a:
        start = parse_hm(await current("WORK_START"))
        return await reply(
            f"Ish boshlanishi: {hm_str(start) if start is not None else '-'}. "
            "O'zgartirish: /vaqt 09:00"
        )
    if cmd == "kechikish" and not a:
        return await reply(
            f"Hozir {await current('GRACE_MIN')} daqiqa. O'zgartirish: /kechikish 15"
        )
    key = {"vaqt": "WORK_START", "kechikish": "GRACE_MIN"}.get(cmd) or (a[0].upper() if a else "")
    val = " ".join(a if cmd != "dsozla" else a[1:])
    if key not in SETTING_KEYS or not val:
        return await reply("Format: /dsozla KALIT qiymat. Kalitlar: /dsozlamalar")
    try:
        s = await api.call("PUT", f"hr/settings/{key}/", actor=uid, json={"value": val})
    except api.ServiceRefusal as err:
        return await reply("❌ " + esc(err.detail))
    await reply(f"✅ {s['label']}: <b>{esc(s['value'])}</b>")


async def notify_employee(uid: int, ref, what: str) -> None:
    """Ask the backend to tell the employee (hr.hours_set / hr.off_days_set -> DM)."""
    await api.call("POST", emp_path(ref) + "notify/", actor=uid, json={"what": what})


async def _work_hours(a: list[str], uid: int, reply: Reply, need_emp) -> None:
    if not a:
        return await reply(IV_TITLE, K.emp_picker_kb(await active_employees(uid), 0, "iv"))
    e = await need_emp()
    if not e:
        return
    if len(a) > 1 and a[1].lower() == "umumiy":
        e = await api.call("PATCH", emp_path(a[0]), actor=uid, json={"reset_hours": True})
        await notify_employee(uid, a[0], "hours")
        return await reply(f"✅ {esc(e['name'])}: umumiy vaqt {e['hours_label']}")
    t1, t2 = (a[1] if len(a) > 1 else None), (a[2] if len(a) > 2 else None)
    if t1 and not t2 and re.fullmatch(r"\d{1,2}(:\d\d)?-\d{1,2}(:\d\d)?", t1):
        t1, t2 = t1.split("-")

    def fix(t):
        return f"{t}:00" if t and re.fullmatch(r"\d{1,2}", t) else t

    s1, s2 = parse_hm(fix(t1)), parse_hm(fix(t2))
    if s1 is None or s2 is None or s2 <= s1:
        return await reply(
            "Format: /ishvaqti 5 10:00 19:00 (yoki /ishvaqti 5 10-19, /ishvaqti 5 umumiy)"
        )
    e = await api.call(
        "PATCH",
        emp_path(a[0]),
        actor=uid,
        json={"work_start": hm_str(s1), "work_end": hm_str(s2)},
    )
    await notify_employee(uid, a[0], "hours")
    await reply(f"✅ {esc(e['name'])}: ish vaqti {e['hours_label']}")


async def _points(a: list[str], uid: int, reply: Reply, need_emp) -> None:
    e = await need_emp()
    if not e:
        return
    try:
        v = int(str(a[1] if len(a) > 1 else "").replace("−", "-"))
    except ValueError:
        v = 0
    if not v or abs(v) > 100:
        return await reply("Format: /ball 5 +10 sabab (yoki /ball 5 -5 sabab), ko'pi bilan 100")
    why = " ".join(a[2:])
    # the backend emits hr.points_added, which DMs the employee (hr/notify.py)
    await api.call(
        "POST", "hr/points/", actor=uid, json={"employee": a[0], "value": v, "reason": why}
    )
    await reply(f"✅ {esc(e['name'])}: {v:+d} ball" + (f" ({esc(why)})" if why else ""))

