"""`hr.*` events from the backend (POST /notify, docs/BOT_CONTRACT.md section 1.5).

The backend sends data only (who, when, numbers); the wording, buttons and phrase pools
live here. Every renderer reports one `delivered` entry per send through the Notifier
(`blocked` included), so the backend can keep Employee.can_dm right
(hr.services.record_dm_results) and the schedule can count an ask only when delivered.
"""

from __future__ import annotations

import random
from datetime import date

from bot.notify.registry import Notifier, on

from . import keyboards as K
from . import reports as R
from .fmt import days_label, esc, fmt_day, fmt_min, ism, month_name
from .texts import TXT


def _day(iso: str) -> date:
    return date.fromisoformat(iso)


def _emp(d: dict) -> tuple[int, str]:
    e = d["employee"]
    return e["telegram_id"], ism(e["name"])


# ------------------------------------------------------------------ schedule: groups
@on("hr.morning")
async def morning(n: Notifier, d: dict) -> None:
    starts = d["starts"]
    t = (
        f"☀️ <b>Xayrli tong, jamoa!</b>\n\n{random.choice(TXT['morning'])}\n\n⏰ "
        + (
            f"Ish soat <b>{starts[0]}</b> da boshlanadi. "
            if len(starts) == 1
            else "Ish boshlanishi: "
            + " / ".join(f"<b>{x}</b>" for x in starts)
            + " (har kimning o'z vaqti). "
        )
        + "Kelganingizda shu yerga <b>video-doiracha</b> tashlang."
    )
    if d.get("uniform_check"):
        t += "\n" + random.choice(TXT["uniform"])
    await n.send(d["chat_id"], t)


@on("hr.missing_list")
async def missing_list(n: Notifier, d: dict) -> None:
    names = ", ".join(esc(x) for x in d["names"])
    await n.send(d["chat_id"], "⏰ Ish boshlandi. Hali otchet tashlamaganlar: " + names)


# ------------------------------------------------------------------ schedule: employees (sync)
@on("hr.ask_eta")
async def ask_eta(n: Notifier, d: dict) -> None:
    tg, name = _emp(d)
    if d.get("repeat"):
        t = (
            f"{name}, hali ham video-doirachangizni ko'rmadim. 🤔\n"
            "Hammasi joyidami? Qancha vaqtda yetib kelasiz?"
        )
    else:
        t = (
            f"Assalomu alaykum, {name}! 👋\nIsh soat {d['start']} da boshlandi, guruhda hali "
            "video-doirachangizni ko'rmadim. Hammasi joyidami?\n"
            "Ishga qancha vaqtda yetib kelasiz? Tugmani bosing yoki yozing "
            "(masalan: <i>20 daqiqa</i> yoki <i>10:30</i>)."
        )
    await n.send(tg, t, K.eta_kb(d["day"]))


@on("hr.out_reminder")
async def out_reminder(n: Notifier, d: dict) -> None:
    tg, name = _emp(d)
    await n.send(
        tg,
        f"{name}, ish kuningiz yakunlandi, rahmat! 🙏\nKetayotganingizda guruhga "
        "<b>video-doiracha</b> tashlashni unutmang, ketish vaqtingiz shunda qayd etiladi. 🙂",
    )


@on("hr.eta_passed")
async def eta_passed(n: Notifier, d: dict) -> None:
    tg, name = _emp(d)
    await n.send(
        tg,
        f"{name}, siz soat {d['eta']} da yetib kelaman degan edingiz, lekin guruhda "
        "video-doiracha hali yo'q. ⏳\n"
        "Yetib kelgan bo'lsangiz guruhga tashlang. Yana qancha vaqt kerak?",
        K.eta_kb(d["day"]),
    )


# ------------------------------------------------------------------ schedule: managers
@on("hr.day_report")
async def day_report(n: Notifier, d: dict) -> None:
    text = R.render_day(d["report"], f"📊 Kunlik hisobot ({d['now_hm']})")
    await n.many(d["admins"], text)


@on("hr.month_report")
async def month_report(n: Notifier, d: dict) -> None:
    text = (
        R.period_report(d["report"], f"🗓 Oylik hisobot ({d['ym']})")
        + f"\n\n🌐 To'liq jadval saytda: {d['site_url']}"
    )
    await n.many(d["admins"], text)


@on("hr.winner_pick")
async def winner_pick(n: Notifier, d: dict) -> None:
    kind, period, rows = d["kind"], d["period"], d["rows"]
    if not rows:
        return
    if kind == "m":
        text = R.month_winner_text(period, rows)
    else:
        text = R.year_report(period, rows)
    await n.many(d["admins"], text, K.winner_kb(kind, period, rows))


@on("hr.holiday_ask")
async def holiday_ask(n: Notifier, d: dict) -> None:
    text = f"🎉 <b>{fmt_day(_day(d['day']))}</b> — {esc(d['name'])}.\nDam olinadimi? Necha kun?"
    await n.many(d["admins"], text, K.holiday_ask_kb(d["day"]))


# ------------------------------------------------------------------ live alerts and requests
@on("hr.live_alert")
async def live_alert(n: Notifier, d: dict) -> None:
    kind, e, x = d["kind"], d["employee"], d.get("data") or {}
    name = esc(e["name"])
    if kind == "late":
        text = (
            f"⏰ <b>{name}</b> ({esc(x.get('group_title'))}) kech keldi: {x['in_time']} "
            f'(+{fmt_min(x["late_min"])}). <a href="{x["link"]}">Otchet</a>'
        )
    elif kind == "late_comment":
        text = (
            f"📝 <b>{name}</b> kechikish sababi: <b>{x.get('late_reason') or '-'}</b>\n"
            f"Izoh: {esc(x.get('comment'))}"
        )
    elif kind == "eta":
        text = f"🕐 {name}: taxminan <b>{x['eta']}</b> da yetib kelaman dedi."
    elif kind == "excused":
        text = f"📝 <b>{name}</b> bugun kela olmasligini aytdi.\nSabab: {esc(x.get('reason'))}"
    else:
        raise ValueError(f"unknown live alert kind {kind!r}")
    await n.many(d["admins"], text)


@on("hr.off_request")
async def off_request(n: Notifier, d: dict) -> None:
    e = d["employee"]
    text = (
        f"😴 <b>{esc(e['name'])}</b> bugun ({fmt_day(_day(d['day']))}) dam olish kunim "
        "deyapti. Tasdiqlaysizmi?"
    )
    await n.many(d["admins"], text, K.off_request_kb(d["day"], e["telegram_id"]))


@on("hr.off_request_answered")
async def off_request_answered(n: Notifier, d: dict) -> None:
    tg, name = _emp(d)
    if d.get("approve"):
        t = (
            f"✅ {name}, rahbar tasdiqladi: bugun dam olish kuningiz. "
            "Yaxshi dam oling, kuch to'plang! 😊"
        )
    else:
        t = (
            f"{name}, afsuski rahbar bugungi dam kunini tasdiqlamadi. Iltimos, ishga keling va "
            "guruhga video-doiracha tashlang. Tushunganingiz uchun rahmat! 🙏"
        )
    await n.send(tg, t)


@on("hr.employee_left")
async def employee_left(n: Notifier, d: dict) -> None:
    await n.many(d["admins"], f"👋 {esc(d['name'])} guruhdan chiqdi va ro'yxatdan olib tashlandi.")


@on("hr.bot_added_to_group")
async def bot_added_to_group(n: Notifier, d: dict) -> None:
    await n.many(
        d["admins"],
        f'🤖 Bot "{esc(d["title"])}" guruhiga qo\'shildi. '
        "Kuzatishni boshlash uchun o'sha guruhda /ulash yozing.",
    )


# ------------------------------------------------------------------ manager actions -> employee
@on("hr.points_added")
async def points_added(n: Notifier, d: dict) -> None:
    tg, name = _emp(d)
    v, why = d["value"], d.get("reason") or ""
    if v > 0:
        t = (
            f"🌟 {name}, rahbar sizga <b>+{v} ball</b> berdi"
            + (f": {esc(why)}" if why else "")
            + ". Barakalla, shunday davom eting! 👏"
        )
    else:
        t = (
            f"ℹ️ {name}, sizga <b>{v} ball</b> yozildi"
            + (f": {esc(why)}" if why else "")
            + ". Keyingi safar albatta yaxshiroq bo'ladi, ishonamiz. 🙏"
        )
    await n.send(tg, t)


@on("hr.winner_announced")
async def winner_announced(n: Notifier, d: dict) -> None:
    kind, period = d["kind"], d["period"]
    tg, name = _emp(d)
    what = (
        f"🏆 <b>{month_name(period)} oyining eng yaxshi xodimi</b>"
        if kind == "m"
        else f"👑 <b>{period}-yilning eng yaxshi xodimi</b>"
    )
    t = (
        f"🎉 Hurmatli jamoa!\n\n{what} — <b>{esc(d['employee']['name'])}</b>! 👏\n"
        f"⭐ {d['pts']} ball · intizom {d['disc']}%\n\n"
        + random.choice(TXT["winner"])
        + "\n\nKeyingi g'olib siz bo'lishingiz mumkin! 💪"
    )
    await n.many(d.get("groups") or [], t)
    await n.send(
        tg,
        f"🎉 {name}, tabriklaymiz! Siz "
        + (f"{month_name(period)} oyining" if kind == "m" else f"{period}-yilning")
        + " eng yaxshi xodimi deb topildingiz! 🏆\nIntizomingiz va mehnatingiz uchun katta "
        "rahmat. Jamoamiz siz bilan faxrlanadi! 🙏",
    )


@on("hr.holiday_applied")
async def holiday_applied(n: Notifier, d: dict) -> None:
    hol_day, name, days = _day(d["hol_day"]), d["name"], [_day(x) for x in d.get("days") or []]
    if not d["n"] or not days:
        await n.many(d["admins"], f"✅ {fmt_day(hol_day)} ({esc(name)}) — ish kuni, dam olinmaydi.")
        return
    txt = fmt_day(days[0]) if len(days) == 1 else f"{fmt_day(days[0])} — {fmt_day(days[-1])}"
    await n.many(
        d["admins"],
        f"✅ Dam olish belgilandi: <b>{txt}</b> ({d['n']} kun). "
        "Bu kunlarda xodimlardan otchet so'ralmaydi.",
    )
    await n.many(
        d.get("groups") or [],
        f"🎉 Hurmatli jamoa! {esc(name)} munosabati bilan <b>{txt}</b> dam olish kunlari. "
        "Bayramingiz muborak bo'lsin! 🎊",
    )


@on("hr.day_off_set")
async def day_off_set(n: Notifier, d: dict) -> None:
    tg, name = _emp(d)
    await n.send(tg, f"ℹ️ {name}, {fmt_day(_day(d['day']))} siz uchun dam olish kuni deb belgilandi.")


@on("hr.leave_added")
async def leave_added(n: Notifier, d: dict) -> None:
    tg, name = _emp(d)
    await n.send(
        tg,
        f"ℹ️ {name}, sizga {d['date_from']} — {d['date_to']} kunlari belgilandi: "
        f"{esc(d['reason'])}.",
    )


@on("hr.hours_set")
async def hours_set(n: Notifier, d: dict) -> None:
    tg, name = _emp(d)
    e = d["employee"]
    await n.send(
        tg,
        f"ℹ️ {name}, ish vaqtingiz belgilandi: <b>{e['hours_label']}</b>. "
        f"<b>{e['ontime_until']}</b> gacha kelsangiz vaqtida hisoblanadi. "
        "Kelganda va ketayotganda guruhga video-doiracha tashlang. 🙂",
    )


@on("hr.off_days_set")
async def off_days_set(n: Notifier, d: dict) -> None:
    tg, name = _emp(d)
    off = d["employee"].get("off_days") or []
    await n.send(tg, f"ℹ️ {name}, sizning dam olish kunlaringiz: <b>{days_label(off)}</b>")
