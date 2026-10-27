"""Davomat bot (port of DV.handle in davomat.txt).

handle(update) -> True when the update belongs to davomat (group reports, member
joins/leaves, `dv:` buttons, davomat commands, answers the bot is waiting for);
False lets the finance bot have it. claims() is the cheap pre-check the webhook
uses to answer Telegram right away.
"""

from __future__ import annotations

import logging
import random
import re
from datetime import date, datetime, timedelta

from accounting.telegram import api
from core.telegram import bot_link as core_bot_link

from . import reports as R
from . import services as S
from .constants import (
    DEFAULTS,
    ETA_GRACE_MIN,  # noqa: F401 (used by jobs)
    PTS_HELP,
    REASONS,
    ST_LABEL,
    TXT,
    WD_SHORT,
)
from .models import Employee, Holiday, HolidayDecision, Leave, Winner, WorkGroup

log = logging.getLogger("hr.telegram")
esc = R.esc

EMP_CMDS = ["holatim", "kelolmayman", "ballarim", "ballar"]
ADMIN_CMDS = [
    "davomat",
    "dhisobot",
    "dkecha",
    "dhafta",
    "doy",
    "djadval",
    "dxodimlar",
    "damkun",
    "dam",
    "tatil",
    "tatillar",
    "tatil_ochir",
    "bayram",
    "bayramlar",
    "bayram_ochir",
    "dchiqar",
    "dqayta",
    "dsozlamalar",
    "vaqt",
    "kechikish",
    "dsozla",
    "guruhlar",
    "dyordam",
    "ishvaqti",
    "ball",
    "reyting",
    "dtozala",
]
MENU_BTN = "🕘 Davomat"
IV_TITLE = "🕐 Kimning ish vaqtini belgilaymiz?\n(qavsda hozirgi vaqti)"
IV_PRESETS = [("09:00", "18:00"), ("09:00", "19:00"), ("10:00", "19:00")]


# ------------------------------------------------------------------ telegram helpers
def tg(method: str, payload: dict) -> dict | None:
    r = api.call(method, payload)
    return r.get("result") if r.get("ok") else None


def send(chat_id, text: str, kb=None):
    return api.send(chat_id, text, kb)


def dm(e: Employee, text: str, kb=None) -> bool:
    """dm_: private message; remembers when the person blocked the bot."""
    if e.can_dm is False:
        return False
    r = api.send(e.telegram_id, text, kb)
    if r.get("ok"):
        if e.can_dm is not True:
            Employee.objects.filter(pk=e.pk).update(can_dm=True)
            e.can_dm = True
        return True
    if (
        r.get("error_code") == 403
        or "blocked" in str(r.get("description", ""))
        or "chat not found" in str(r.get("description", ""))
    ):
        Employee.objects.filter(pk=e.pk).update(can_dm=False)
        e.can_dm = False
    return False


def notify_admins(text: str, kb=None):
    for tid in S.admin_ids():
        send(tid, text, kb)


def kb(rows) -> dict:
    return {
        "inline_keyboard": [
            [{"text": t, "callback_data": ("dv:" + d)[:64]} for t, d in r] for r in rows if r
        ]
    }


def ism(e: Employee) -> str:
    n = (e.name or "").strip().split()
    return esc(n[0] if n else "hurmatli hamkasb")


def react(chat_id, message_id, emoji: str):
    api.call(
        "setMessageReaction",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": [{"type": "emoji", "emoji": emoji}],
        },
    )


def bot_link() -> str:
    return core_bot_link("davomat")


def msg_link(chat: dict, mid: int) -> str:
    if chat.get("username"):
        return f"https://t.me/{chat['username']}/{mid}"
    cid = re.sub(r"^-100|^-", "", str(chat["id"]))
    return f"https://t.me/c/{cid}/{mid}"


def parse_cmd(text: str):
    parts = str(text).strip().split()
    return parts[0][1:].split("@")[0].lower(), parts[1:]


def uniform_kb(day: date):
    d = day.isoformat()
    return kb([[("👕 Ha, formadaman", f"uni:{d}:1"), ("Yo'q", f"uni:{d}:0")]])


def eta_kb(day: date):
    d = day.isoformat()
    return kb(
        [
            [
                ("10 daqiqa", f"eta:{d}:10"),
                ("20 daqiqa", f"eta:{d}:20"),
                ("30 daqiqa", f"eta:{d}:30"),
            ],
            [("1 soat", f"eta:{d}:60"), ("2 soat", f"eta:{d}:120")],
            [("✅ Keldim, otchet tashlayman", f"here:{d}")],
            [("😴 Bugun dam olish kunim", f"offreq:{d}")],
            [("🚫 Bugun kela olmayman", f"cant:{d}")],
        ]
    )


def reason_kb(day: date):
    d = day.isoformat()
    rows = [[(v, f"rsn:{d}:{k}")] for k, v in REASONS.items()]
    rows.append([("✏️ Boshqa (o'zim yozaman)", f"rsn:{d}:other")])
    return kb(rows)


# ------------------------------------------------------------------ routing
def claims(up: dict) -> bool:
    """Cheap: does davomat want this update? (must agree with handle())"""
    if up.get("my_chat_member") or up.get("chat_member"):
        return True
    cq = up.get("callback_query")
    if cq:
        return str(cq.get("data") or "").startswith("dv:")
    m = up.get("message")
    if not m or not m.get("from"):
        return False
    ctype = (m.get("chat") or {}).get("type")
    if ctype in ("group", "supergroup"):
        return True
    if ctype != "private":
        return False
    text = str(m.get("text") or "").strip()
    uid = m["from"]["id"]
    if text.startswith("/"):
        cmd, args = parse_cmd(text)
        if cmd == "start":
            return (args[:1] == ["davomat"]) or (
                not args and not S.finance_member(uid) and S.emp(uid) is not None
            )
        if cmd in EMP_CMDS:
            return True
        return cmd in ADMIN_CMDS and S.is_admin(uid)
    if text == MENU_BTN and S.is_admin(uid):
        return True
    if S.is_admin(uid) and S.state(f"AWAIT_{uid}"):
        return True
    e = S.emp(uid)
    if not e:
        return False
    a = S.att(S.now().date(), e)
    return bool(a and (a.wait or a.asked or a.eta))


def handle(up: dict) -> bool:
    try:
        return _route(up)
    except Exception:  # noqa: BLE001
        log.exception("davomat update failed")
        cq, m = up.get("callback_query"), up.get("message")
        return bool(cq and str(cq.get("data") or "").startswith("dv:")) or bool(
            m and (m.get("chat") or {}).get("type") not in (None, "private")
        )


def _route(up: dict) -> bool:
    cq = up.get("callback_query")
    if cq:
        if not str(cq.get("data") or "").startswith("dv:"):
            return False
        on_callback(cq)
        return True
    if up.get("my_chat_member"):
        on_my_chat_member(up["my_chat_member"])
        return True
    if up.get("chat_member"):
        on_chat_member(up["chat_member"])
        return True
    m = up.get("message")
    if not m or not m.get("from"):
        return False
    text = str(m.get("text") or "").strip()
    ctype = m["chat"].get("type")
    if ctype in ("group", "supergroup"):
        if text.startswith("/"):
            on_group_command(m)
        elif m.get("new_chat_members"):
            on_new_members(m)
        elif m.get("left_chat_member"):
            on_left_member(m)
        else:
            on_group_message(m)
        return True
    if ctype != "private":
        return False
    uid = m["from"]["id"]
    e = S.emp(uid)
    if e and e.can_dm is not True:  # they wrote to the bot → it can write back
        Employee.objects.filter(pk=e.pk).update(can_dm=True)
        e.can_dm = True
    if text.startswith("/"):
        cmd, args = parse_cmd(text)
        if cmd == "start":
            if args[:1] == ["davomat"]:
                return employee_start(m, True)
            if not args and not S.finance_member(uid):
                return employee_start(m, False)
            return False
        if cmd in EMP_CMDS:
            on_private_command(m)
            return True
        if cmd in ADMIN_CMDS and S.is_admin(uid):
            admin_command(cmd, args, uid)
            return True
        return False
    if text == MENU_BTN and S.is_admin(uid):
        admin_menu(uid)
        return True
    return on_private_text(m)


# ------------------------------------------------------------------ group
def on_group_message(m: dict):
    user = m["from"]
    group = S.group_by_chat(m["chat"]["id"])
    if user.get("is_bot") or not group or S.is_admin(user["id"]):
        return
    e, _ = S.upsert_emp(user, group)
    at = S.from_unix(m.get("date") or 0)
    day, at_min = at.date(), S.mod(at)
    if at_min < (S.parse_hm(S.setting("CHECKIN_FROM")) or 300):
        return
    if m.get("forward_origin") or m.get("forward_date") or m.get("forward_from"):
        return  # a forwarded report doesn't count
    mode = S.setting("CHECKIN_MODE").lower()
    is_vn = bool(m.get("video_note"))
    has_media = any(m.get(k) for k in ("photo", "video", "video_note", "location", "venue"))
    txt = str(m.get("text") or m.get("caption") or "").lower()
    kws = [k.strip() for k in S.setting("KEYWORDS").lower().split(",") if k.strip()]
    has_kw = any(k in txt for k in kws)
    if mode == "video_note":
        ok = is_vn
    elif mode == "media":
        ok = has_media
    elif mode == "keyword":
        ok = has_kw
    elif mode == "any":
        ok = has_media or bool(txt.strip())
    else:
        ok = has_media or has_kw
    sn = S.since()
    if sn and day < sn:
        return
    if not S.expected_today(e, day):
        return
    a = S.att(day, e)
    real = ok and (mode != "any" or has_media)
    if a and a.in_time:
        if real:
            on_checkout(m, e, day, a, at, at_min)
        return
    # no check-in, but less than 2h to the end of the day: this is the leaving report
    if real and ((a and a.out_time) or at_min >= S.emp_end(e) - 120):
        first = not (a and a.out_time)
        S.set_att(day, e, out_time=S.to_time(at_min), no_checkin=True, wait="")
        if S.setting("GROUP_ACK") == "reaction":
            react(m["chat"]["id"], m["message_id"], "🫡")
        if first:
            dm(
                e,
                f"Rahmat, {ism(e)}! Ketish vaqtingiz qayd etildi: <b>{S.hm_str(at_min)}</b>.\n"
                "Lekin bugun ertalab kelish otchetingizni ko'rmadim. 🤔 Iltimos, ertaga ishga kelganingizda ham guruhga <b>video-doiracha</b> tashlang. Yaxshi dam oling! 🌙",
            )
        return
    if not ok:
        if mode == "video_note" and (has_media or has_kw) and not (a and a.warned):
            S.set_att(day, e, warned=True)
            dm(
                e,
                f"{ism(e)}, otchetingizni ko'rdim, rahmat! 🙂 Faqat bitta iltimos: otchet <b>video-doiracha</b> (dumaloq video) ko'rinishida bo'lishi kerak. "
                "Guruhga qaytadan dumaloq video tashlab yuboring (Telegramda mikrofon tugmasini bir marta bossangiz, kamera belgisiga o'tadi).",
            )
        return
    start = S.emp_start(e)
    late = at_min - start
    st = "on_time" if late <= S.setting_int("GRACE_MIN") else "late"
    link = msg_link(m["chat"], m["message_id"])
    S.set_att(
        day,
        e,
        in_time=S.to_time(at_min),
        late_min=max(late, 0),
        status=st,
        link=link,
        wait="lr" if st == "late" else "",
        work_start=S.hm_str(start),
        work_end=S.hm_str(S.emp_end(e)),
        group_title=group.title,
    )
    ack = S.setting("GROUP_ACK")
    if ack == "reaction":
        react(m["chat"]["id"], m["message_id"], "🔥" if st == "on_time" else "✍")
    elif ack == "reply":
        api.call(
            "sendMessage",
            {
                "chat_id": m["chat"]["id"],
                "reply_to_message_id": m["message_id"],
                "text": (
                    f"✅ Qabul qilindi, {S.hm_str(at_min)} — vaqtida"
                    if st == "on_time"
                    else f"⏰ Qabul qilindi, {S.hm_str(at_min)} — {S.fmt_min(late)} kechikish"
                ),
            },
        )
    if st == "on_time":
        t = (
            f"Xayrli tong, {ism(e)}! ☀️\nOtchetingiz qabul qilindi, kelgan vaqtingiz: <b>{S.hm_str(at_min)}</b>.\n"
            + random.choice(TXT["praise"])
        )
        if S.setting_bool("UNIFORM_CHECK"):
            dm(e, t + "\n\n👕 Bugun formadamisiz?", uniform_kb(day))
        else:
            dm(e, t)
    else:
        d = day.isoformat()
        dm(
            e,
            f"{ism(e)}, otchetingiz qabul qilindi, kelgan vaqtingiz: <b>{S.hm_str(at_min)}</b>.\n⏰ Bugun <b>{S.fmt_min(late)}</b> kechikib keldingiz.\n\n"
            "Hammasi joyidami? Kechikishga uzrli sabab bo'ldimi?",
            kb([[("✅ Sababli", f"lr:{d}:1"), ("❌ Sababsiz", f"lr:{d}:0")]]),
        )
        if S.setting_bool("MANAGER_LIVE_ALERTS"):
            notify_admins(
                f"⏰ <b>{esc(e.name)}</b> ({esc(group.title)}) kech keldi: {S.hm_str(at_min)} (+{S.fmt_min(late)}). "
                f'<a href="{link}">Otchet</a>'
            )


def on_checkout(m: dict, e: Employee, day: date, a, at: datetime, at_min: int):
    """onCheckout_: a video note at least OUT_MIN_GAP after arrival = leaving."""
    in_min = S.parse_hm(a.in_time)
    if at_min - in_min < S.setting_int("OUT_MIN_GAP"):
        return
    end = S.parse_hm(a.work_end) if a.work_end else S.emp_end(e)
    early = max(end - at_min, 0)
    is_early = early > S.setting_int("LEAVE_GRACE_MIN")
    first = a.out_time is None
    wait = "er" if is_early and not a.early_reason else ("" if a.wait in ("er", "ec") else a.wait)
    S.set_att(
        day,
        e,
        out_time=S.to_time(at_min),
        early_min=early if is_early else 0,
        early_reason=a.early_reason if is_early else "",
        wait=wait,
    )
    if S.setting("GROUP_ACK") == "reaction":
        react(m["chat"]["id"], m["message_id"], "✍" if is_early else "🫡")
    if not first and not is_early:
        return
    if not is_early:
        dm(
            e,
            f"Rahmat, {ism(e)}! 🙏 Ketish vaqtingiz qayd etildi: <b>{S.hm_str(at_min)}</b>.\n"
            + random.choice(TXT["bye"]),
        )
        return
    if a.early_reason:
        return
    d = day.isoformat()
    dm(
        e,
        f"{ism(e)}, ketish vaqtingiz qayd etildi: <b>{S.hm_str(at_min)}</b>.\n🚪 Ish vaqtingiz <b>{S.hm_str(end)}</b> gacha edi, ya'ni <b>"
        f"{S.fmt_min(early)}</b> erta ketyapsiz.\n\nRahbar bilan kelishilganmi yoki uzrli sabab bormi?",
        kb([[("✅ Sababli / kelishilgan", f"er:{d}:1"), ("❌ Sababsiz", f"er:{d}:0")]]),
    )


def on_new_members(m: dict):
    group = S.group_by_chat(m["chat"]["id"])
    if not group:
        return
    for u in m["new_chat_members"]:
        if u.get("is_bot") or S.is_admin(u["id"]):
            continue
        e, is_new = S.upsert_emp(u, group)
        if is_new or e.can_dm is not True:
            send(
                m["chat"]["id"],
                f"Xush kelibsiz, {esc(e.name)}! 👋\nHar kuni ishga kelganingizda shu guruhga <b>video-doiracha</b> otchet tashlang.\n"
                "Eslatmalarni olish uchun botga ulaning 👇",
                {"inline_keyboard": [[{"text": "🤖 Botga ulanish", "url": bot_link()}]]},
            )


def on_left_member(m: dict):
    u = m.get("left_chat_member")
    group = S.group_by_chat(m["chat"]["id"])
    if not group or not u or u.get("is_bot"):
        return
    e = S.emp(u["id"])
    if e and e.is_active and e.group_id == group.id:
        e.is_active = False
        e.save(update_fields=["is_active"])
        notify_admins(f"👋 {esc(e.name)} guruhdan chiqdi va ro'yxatdan olib tashlandi.")


def on_chat_member(cm: dict):
    u = (cm.get("new_chat_member") or {}).get("user")
    if not u or u.get("is_bot") or not S.group_by_chat(cm["chat"]["id"]):
        return
    if cm["new_chat_member"].get("status") in ("left", "kicked"):
        on_left_member({"chat": cm["chat"], "left_chat_member": u})


def on_my_chat_member(mcm: dict):
    st = (mcm.get("new_chat_member") or {}).get("status")
    chat = mcm.get("chat") or {}
    if (
        chat.get("type") in ("group", "supergroup")
        and st in ("member", "administrator")
        and not S.group_by_chat(chat["id"])
    ):
        notify_admins(
            f'🤖 Bot "{esc(chat.get("title"))}" guruhiga qo\'shildi. Kuzatishni boshlash uchun o\'sha guruhda /ulash yozing.'
        )


def on_group_command(m: dict):
    cmd, _ = parse_cmd(m["text"])
    chat, uid = m["chat"], m["from"]["id"]
    if cmd == "myid":
        return send(
            chat["id"], f"Chat ID: <code>{chat['id']}</code>\nSizning ID: <code>{uid}</code>"
        )
    if not S.is_admin(uid):
        return
    if cmd == "ulash":
        WorkGroup.objects.update_or_create(
            chat_id=chat["id"],
            defaults={"title": chat.get("title") or str(chat["id"]), "is_active": True},
        )
        warn = ""
        me = tg("getMe", {}) or {}
        if not me.get("can_read_all_group_messages"):
            cmb = tg("getChatMember", {"chat_id": chat["id"], "user_id": me.get("id")}) or {}
            if cmb.get("status") != "administrator":
                warn = (
                    "\n\n⚠️ Bot barcha xabarlarni ko'rishi uchun uni guruhda <b>admin</b> qiling."
                )
        send(uid, f'✅ "{esc(chat.get("title"))}" guruhi kuzatuvga olindi.{warn}')
        send(
            chat["id"],
            "Hurmatli xodimlar! Har kuni ishga kelganingizda shu guruhga <b>video-doiracha</b> otchet tashlang. "
            "Eslatmalarni olish uchun botga ulaning 👇",
            {"inline_keyboard": [[{"text": "🤖 Botga ulanish", "url": bot_link()}]]},
        )
    elif cmd == "uzish":
        WorkGroup.objects.filter(chat_id=chat["id"]).update(is_active=False)
        send(uid, f'"{esc(chat.get("title"))}" guruhi kuzatuvdan chiqarildi.')
    elif cmd == "qosh":
        r = m.get("reply_to_message") or {}
        if r.get("from") and not r["from"].get("is_bot"):
            e, _ = S.upsert_emp(r["from"], S.group_by_chat(chat["id"]))
            send(uid, f"✅ {esc(e.name)} ro'yxatga qo'shildi (#{e.number}).")


# ------------------------------------------------------------------ private
def on_private_command(m: dict):
    cmd, _ = parse_cmd(m["text"])
    uid = m["from"]["id"]
    if cmd in ("holatim", "ballarim"):
        return my_status(uid)
    if cmd == "ballar":
        return send(uid, PTS_HELP)
    if cmd == "kelolmayman":
        e = S.emp(uid)
        if not e:
            return send(uid, "Siz davomat ro'yxatida yo'qsiz.")
        day = S.now().date()
        a = S.att(day, e)
        if a and a.in_time:
            return send(uid, "Siz bugun allaqachon otchet tashlagansiz. 🙂")
        S.set_att(day, e, wait="reason")
        return send(
            uid,
            f"Tushunarli, {ism(e)}. Iltimos, sababini tanlang yoki yozib yuboring:",
            reason_kb(day),
        )


def employee_start(m: dict, via_link: bool) -> bool:
    uid = m["from"]["id"]
    e = S.emp(uid)
    if not e:
        for g in S.groups():
            mem = tg("getChatMember", {"chat_id": g.chat_id, "user_id": uid}) or {}
            if mem.get("status") in ("member", "administrator", "creator", "restricted"):
                e, _ = S.upsert_emp(m["from"], g)
                break
    if not e:
        if not via_link:
            return False
        send(
            uid,
            "Assalomu alaykum! Siz ish guruhlarida topilmadingiz. Avval ish guruhiga qo'shiling, keyin qayta /start bosing.",
        )
        return True
    e.can_dm, e.is_active = True, True
    e.save(update_fields=["can_dm", "is_active"])
    general = S.parse_days(S.setting("OFF_DAYS"))
    off = (
        S.days_label(e.off_days)
        if e.off_days
        else (S.days_label(general) if general else "rahbar belgilaydi")
    )
    send(
        uid,
        f"Assalomu alaykum, {ism(e)}! 👋\nMen SerMebel jamoasining davomat yordamchisiman. Endi ish vaqti bo'yicha siz bilan shu yerda muloqot qilamiz. ✅\n\n"
        "Qanday ishlaydi:\n• Ishga kelganingizda guruhga <b>video-doiracha</b> tashlang.\n"
        f"• Ish vaqtingiz: <b>{S.emp_hours(e)}</b>. <b>{S.hm_str(S.emp_start(e) + S.setting_int('GRACE_MIN'))}</b> gacha kelsangiz vaqtida hisoblanadi.\n"
        "• Ketayotganda ham guruhga <b>video-doiracha</b> tashlang.\n"
        "• Har kuni ball yig'asiz, oy oxirida eng yaxshisi <b>🏆 Oy xodimi</b> bo'ladi. /ballarim\n"
        f"• Kechiksangiz, sababini so'rayman.\n• Kela olmasangiz /kelolmayman yuboring.\n• Dam kuningiz: <b>{off}</b>\n\n/holatim - holatingiz",
    )
    return True


def my_status(uid: int):
    e = S.emp(uid)
    if not e:
        return send(uid, "Siz xodimlar ro'yxatida yo'qsiz.")
    now_d = S.now()
    day = now_d.date()
    r = next((x for x in S.compute_day(day, now_d) if x.e.id == e.id), None)
    allst = S.month_stats(day.strftime("%Y-%m"), now_d)
    idx = next((i for i, s in enumerate(allst) if s.e.id == e.id), -1)
    L = [
        f"<b>{esc(e.name)}</b>",
        f"🕐 Ish vaqtingiz: <b>{S.emp_hours(e)}</b>",
        "🗓 Bugun: "
        + (
            ST_LABEL.get(r.st, r.st)
            + (f", keldi {S.hm(r.g('in_time'))}" if r.g("in_time") else "")
            + (f", ketdi {S.hm(r.g('out_time'))}" if r.g("out_time") else "")
            if r
            else "-"
        ),
    ]
    if idx >= 0:
        st = allst[idx]
        L += [
            "",
            "<b>Shu oy:</b>",
            f"⭐ Ball: <b>{st.pts}</b> · reytingda <b>{idx + 1}-o'rin</b> ({len(allst)} kishidan)",
            f"✅ Vaqtida: {st.on_time} · ⏰ Kech: {st.late}"
            + (f" (jami {S.fmt_min(st.late_min)})" if st.late_min else ""),
            f"❌ Kelmadi: {st.absent} · 📝 Sababli: {st.excused} · 🚪 Erta ketdi: {st.early_n}",
            f"📈 Intizom: <b>{st.disc}%</b>",
            "",
            "Ballar qanday hisoblanadi: /ballar",
        ]
    send(uid, "\n".join(L))


def _looks_finance(text: str) -> bool:
    """«350000 furnitura 406» is a finance entry; «20 daqiqa» is an ETA."""
    from accounting.text import parse_quick

    try:
        q = parse_quick(text, [], [])
        return bool(q) and (q["val"] >= 1000 or q["cur"] == "USD")
    except Exception:  # noqa: BLE001
        return False


def on_private_text(m: dict) -> bool:
    uid = m["from"]["id"]
    text = str(m.get("text") or "").strip()
    if not text:
        return False
    aw = S.state(f"AWAIT_{uid}") if S.is_admin(uid) else None
    if aw:
        S.set_state(f"AWAIT_{uid}", None)
        w = aw.split(":")
        mm = re.fullmatch(r"(\d{1,2})(?:\s+(\S+))?", text)
        if w[0] == "hol" and mm:
            hol_day = date.fromisoformat(w[1])
            start = S.parse_date(mm[2], S.now().date()) if mm[2] else hol_day
            announce_holiday(hol_day, int(mm[1]), start or hol_day)
            return True
        return False
    e = S.emp(uid)
    if not e:
        return False
    from accounting.models import BotSession
    from accounting.telegram.router import MENU_ADMIN, MENU_STAFF

    s = BotSession.objects.filter(telegram_id=uid).first()
    if s and s.data:  # a finance flow is in progress — don't steal its answers
        return False
    if text in MENU_STAFF or text in MENU_ADMIN or text in ("📋 Vazifalarim",):
        return False  # a finance menu button, not a lateness comment
    fin = _looks_finance(text)
    now_d = S.now()
    day = now_d.date()
    a = S.att(day, e)
    if not a:
        return False
    if a.wait == "lc" and a.in_time and not fin:
        S.set_att(day, e, late_comment=text[:300], wait="")
        send(
            uid,
            f"Rahmat, {ism(e)}, izohingizni yozib qo'ydim. "
            + (
                "Tushunganingiz uchun rahmat, ishingizga omad! 🙏"
                if a.late_reason == "Sababli"
                else "Ertaga sizni vaqtida kutamiz, ishonaman, uddalaysiz! 💪"
            ),
        )
        if S.setting_bool("MANAGER_LIVE_ALERTS"):
            notify_admins(
                f"📝 <b>{esc(e.name)}</b> kechikish sababi: <b>{a.late_reason or '-'}</b>\nIzoh: {esc(text[:300])}"
            )
        if S.setting_bool("UNIFORM_CHECK") and a.uniform is None:
            send(uid, "👕 Bugun formadamisiz?", uniform_kb(day))
        return True
    if a.wait == "ec" and a.out_time and not fin:
        S.set_att(day, e, early_comment=text[:300], wait="")
        send(
            uid,
            f"Rahmat, {ism(e)}, izohingizni yozib qo'ydim. "
            + (
                "Yaxshi dam oling! 🙏"
                if a.early_reason == "Sababli"
                else "Ertaga ish kunini oxirigacha birga yakunlaymiz, degan umiddaman. 💪"
            ),
        )
        return True
    if a.wait == "reason" and not a.in_time and not fin:
        set_excused(e, day, text[:300])
        send(
            uid,
            f"Rahmat, {ism(e)}, oldindan xabar berganingiz yaxshi bo'ldi. Rahbaringizga yetkazdim. Tezroq hammasi joyiga tushsin! 🙏",
        )
        return True
    if not a.in_time and (a.asked or a.eta) and a.status not in ("excused", "off") and not fin:
        eta = S.parse_eta(text, S.mod(now_d))
        if eta is not None:
            set_eta(e, day, eta)
            send(
                uid,
                f"Tushunarli, {ism(e)}. Soat {S.hm_str(eta)} ga kutamiz. Yetib kelishingiz bilan guruhga video-doiracha tashlashni unutmang! 👍",
            )
            return True
    return False


def set_eta(e: Employee, day: date, eta_min: int):
    S.set_att(day, e, eta=S.to_time(eta_min), eta_sent=False, wait="")
    if S.setting_bool("MANAGER_LIVE_ALERTS"):
        notify_admins(
            f"🕐 {esc(e.name)}: taxminan <b>{S.hm_str(eta_min)}</b> da yetib kelaman dedi."
        )


def set_excused(e: Employee, day: date, reason: str):
    S.set_att(day, e, status="excused", excuse=reason or "sabab ko'rsatilmadi", wait="")
    notify_admins(f"📝 <b>{esc(e.name)}</b> bugun kela olmasligini aytdi.\nSabab: {esc(reason)}")


# ------------------------------------------------------------------ buttons
def on_callback(q: dict):
    p = str(q.get("data") or "")[3:].split(":")
    kind, uid = p[0], q["from"]["id"]

    def ans(t="", alert=False):
        api.call(
            "answerCallbackQuery", {"callback_query_id": q["id"], "text": t, "show_alert": alert}
        )

    def clear_kb():
        api.call(
            "editMessageReplyMarkup",
            {
                "chat_id": q["message"]["chat"]["id"],
                "message_id": q["message"]["message_id"],
                "reply_markup": {"inline_keyboard": []},
            },
        )

    if kind in (
        "dk",
        "dkt",
        "dkd",
        "offok",
        "offno",
        "dkp",
        "hol",
        "m",
        "iv",
        "ivs",
        "ivp",
        "ann",
        "rst",
    ):
        if not S.is_admin(uid):
            return ans("Faqat rahbar uchun")
        return admin_callback(q, p, ans)
    e = S.emp(uid)
    if not e:
        return ans("Siz ro'yxatda yo'qsiz")
    today = S.now().date()
    try:
        day = date.fromisoformat(p[1])
    except (IndexError, ValueError):
        return ans()
    if day != today:
        return ans("Bu tugma eskirgan (boshqa kun uchun edi).", True)
    if e.can_dm is not True:
        Employee.objects.filter(pk=e.pk).update(can_dm=True)
    a = S.att(day, e)
    if kind == "uni":
        S.set_att(day, e, uniform=p[2] == "1")
        ans("Rahmat!")
        clear_kb()
        return send(
            uid,
            (
                f"Zo'r, {ism(e)}! Toza va tartibli ko'rinish - professionallik belgisi. 👍"
                if p[2] == "1"
                else f"{ism(e)}, iltimos, formani unutmang. Ertaga albatta forma bilan keling, bu jamoamiz qiyofasi uchun muhim. 🙏"
            ),
        )
    if kind == "lr":
        if not (a and a.in_time):
            return ans()
        lr = "Sababli" if p[2] == "1" else "Sababsiz"
        S.set_att(day, e, late_reason=lr, wait="lc")
        ans()
        clear_kb()
        return send(
            uid,
            (
                f"Tushunarli, {ism(e)}. Sababini qisqacha yozib yuboring:"
                if lr == "Sababli"
                else f"Tushunarli, {ism(e)}. Ochiq javobingiz uchun rahmat. Qisqacha yozing: nima sabab bo'ldi va keyingi safar buning oldini qanday olasiz?"
            ),
        )
    if kind == "er":
        if not (a and a.out_time):
            return ans()
        er = "Sababli" if p[2] == "1" else "Sababsiz"
        S.set_att(day, e, early_reason=er, wait="ec")
        ans()
        clear_kb()
        return send(
            uid,
            (
                f"Tushunarli, {ism(e)}. Qisqacha yozib yuboring: sababi nima yoki kim bilan kelishilgan?"
                if er == "Sababli"
                else f"Tushunarli, {ism(e)}. Ochiq javobingiz uchun rahmat. Qisqacha izoh yozing: nima uchun erta ketishga to'g'ri keldi?"
            ),
        )
    if a and a.in_time:
        ans("Siz bugun otchet tashlagansiz ✅")
        return clear_kb()
    if kind == "eta":
        eta = S.mod(S.now()) + int(p[2])
        set_eta(e, day, eta)
        ans("Qabul qilindi")
        clear_kb()
        return send(
            uid,
            f"Tushunarli, {ism(e)}. Soat {S.hm_str(eta)} ga kutamiz. Yetib kelishingiz bilan guruhga video-doiracha tashlashni unutmang! 👍",
        )
    if kind == "here":
        ans()
        clear_kb()
        return send(
            uid,
            f"Ajoyib, {ism(e)}! Iltimos, hoziroq ish guruhiga video-doiracha tashlang - vaqt o'shanda yoziladi. 👍",
        )
    if kind == "cant":
        S.set_att(day, e, wait="reason")
        ans()
        clear_kb()
        return send(
            uid,
            f"Tushunarli, {ism(e)}. Iltimos, sababini tanlang yoki yozib yuboring:",
            reason_kb(day),
        )
    if kind == "rsn":
        ans()
        clear_kb()
        if p[2] == "other":
            S.set_att(day, e, wait="reason")
            return send(uid, "Sababni qisqacha yozib yuboring:")
        set_excused(e, day, REASONS.get(p[2], p[2]))
        return send(
            uid,
            f"Rahmat, {ism(e)}, oldindan xabar berganingiz yaxshi bo'ldi. Rahbaringizga yetkazdim. Tezroq hammasi joyiga tushsin! 🙏",
        )
    if kind == "offreq":
        S.set_att(day, e, off_requested=True)
        ans()
        clear_kb()
        d = day.isoformat()
        notify_admins(
            f"😴 <b>{esc(e.name)}</b> bugun ({S.fmt_day(day)}) dam olish kunim deyapti. Tasdiqlaysizmi?",
            kb([[("✅ Tasdiqlash", f"offok:{d}:{uid}"), ("❌ Rad etish", f"offno:{d}:{uid}")]]),
        )
        return send(
            uid,
            f"{ism(e)}, so'rovingizni rahbarga yubordim. Javob kelishi bilan shu yerda xabar beraman.",
        )
    ans()


# ------------------------------------------------------------------ admin
ADMIN_HELP = "\n".join(
    [
        "<b>🕘 Davomat — rahbar buyruqlari</b>",
        "",
        "Hisobot har kuni 11:30 da, oylik hisobot oy oxirida o'zi keladi. Hammasi saytda ham: HR bo'limi.",
        "",
        "/davomat — davomat menyusi (yoki «🕘 Davomat» tugmasi)",
        "/dhisobot — hozirgi holat (/dhisobot 20.10.2026)",
        "/dkecha · /dhafta · /doy (/doy 2026-09)",
        "/djadval — saytdagi HR bo'limi havolasi",
        "/dtozala — hisobni noldan boshlash (yozuvlar va ballar o'chadi)",
        "",
        "/ishvaqti — har xodimning ish vaqti (tugmalar bilan) · /ishvaqti 5 10:00 19:00",
        "/reyting — shu oy ballari (/reyting yil — yillik) · /ballar — ballar qoidasi",
        "/ball 5 +10 Mijozdan rahmat oldi — qo'shimcha ball (yoki −5)",
        "",
        "/dxodimlar — ro'yxat",
        "/damkun — dam kunlarini tugmalar bilan belgilash",
        "/dam 5 bugun — bir martalik dam kuni",
        "/tatil 5 25.10.2026 30.10.2026 kasal — ta'til / kasallik",
        "/tatillar · /tatil_ochir 3",
        "/dchiqar 5 · /dqayta 5 — ro'yxatdan chiqarish / qaytarish",
        "/qosh — guruhda xodim xabariga javob qilib yozing",
        "",
        "Bayramdan 3 kun oldin bot o'zi so'raydi: dam olinadimi, necha kun.",
        "/bayram 01.01.2027 Yangi yil · /bayramlar · /bayram_ochir 01.01.2027",
        "",
        "/vaqt 09:00 · /kechikish 15 · /dsozlamalar · /dsozla KALIT qiymat",
        "",
        "/ulash — guruhda yozing, bot shu guruhni kuzatadi (har filialda)",
        "/uzish — kuzatishni to'xtatish · /guruhlar — ulangan guruhlar",
    ]
)


def admin_menu(uid: int):
    send(
        uid,
        "🕘 <b>Davomat</b>\nNimani ko'rasiz?",
        kb(
            [
                [("📊 Bugungi holat", "m:today"), ("📅 Shu oy", "m:month")],
                [("👥 Xodimlar", "m:emps"), ("😴 Dam kunlari", "m:off")],
                [("🕐 Ish vaqtlari", "m:iv"), ("🏆 Reyting", "m:rank")],
                [("🎉 Bayramlar", "m:hol"), ("⚙️ Sozlamalar", "m:set")],
                [("🌐 Saytda ochish", "m:sheet"), ("❓ Buyruqlar", "m:help")],
            ]
        ),
    )


def site_url() -> str:
    from django.conf import settings

    base = (getattr(settings, "SITE_URL", "") or "https://ser-mebel.uz").rstrip("/")
    return f"{base}/hr"


def admin_command(cmd: str, a: list[str], uid: int):
    def reply(t, k=None):
        send(uid, t, k)

    now_d = S.now()
    today = now_d.date()

    def need_emp():
        if not a:
            reply("Xodim raqamini yozing (masalan 5). Ro'yxat: /dxodimlar")
            return None
        e = S.find_emp(a[0])
        if not e:
            reply(f"Xodim topilmadi: {esc(a[0])}. Ro'yxat: /dxodimlar")
        return e

    if cmd == "dyordam":
        return reply(ADMIN_HELP)
    if cmd == "dhisobot":
        d = S.parse_date(a[0], today) if a else today
        if not d:
            return reply("Sana noto'g'ri. Masalan: /dhisobot 20.10.2026")
        return reply(
            R.day_report(today, now_d, "📊 Bugungi hisobot") if d == today else R.past_day_report(d)
        )
    if cmd == "dkecha":
        return reply(R.past_day_report(today - timedelta(days=1)))
    if cmd == "dhafta":
        return reply(
            R.period_report(
                today - timedelta(days=today.isoweekday() - 1), today, now_d, "📅 Haftalik hisobot"
            )
        )
    if cmd == "doy":
        ym = a[0] if a and re.fullmatch(r"\d{4}-\d{2}", a[0]) else today.strftime("%Y-%m")
        return reply(
            R.period_report(
                date.fromisoformat(ym + "-01"),
                S.last_day_of_month(ym),
                now_d,
                f"🗓 Oylik hisobot ({ym})",
            )
        )
    if cmd == "djadval":
        return reply(f"🌐 Davomat jurnali va reyting saytda: {site_url()}")
    if cmd == "dxodimlar":
        emps = S.all_emps()
        if not emps:
            return reply("Hali xodim yo'q. Xodimlar guruhga yozishi bilan avtomatik qo'shiladi.")
        L = [f"<b>👥 Xodimlar ({sum(1 for e in emps if e.is_active)} faol)</b>", ""]
        no_off = 0
        multi = len(S.groups()) > 1
        for e in emps:
            f = [f"🕐 {S.emp_hours(e)}"]
            if not e.is_active:
                f.append("❌ faol emas")
            if e.can_dm is False:
                f.append("⚠️ botga ulanmagan")
            off = S.emp_off_days(e)
            if off:
                f.append("dam: " + ",".join(WD_SHORT[d - 1] for d in off))
            elif e.is_active:
                f.append("dam kuni belgilanmagan")
                no_off += 1
            if multi and e.group:
                f.append(esc(e.group.title))
            L.append(
                f"#{e.number} {esc(e.name)}"
                + (f" @{esc(e.username)}" if e.username else "")
                + " — "
                + ", ".join(f)
            )
        if no_off:
            L += ["", "💡 Dam kunlarini /damkun orqali belgilang."]
        return reply("\n".join(L))
    if cmd == "damkun":
        if len(a) >= 2:
            e = need_emp()
            if not e:
                return
            e.off_days = None if a[1].lower() == "umumiy" else S.parse_days(a[1])
            e.save(update_fields=["off_days"])
            return reply(f"✅ {esc(e.name)} dam kunlari: {S.days_label(S.emp_off_days(e))}")
        return reply("Kimning dam kunlarini belgilaymiz?", emp_picker_kb(0))
    if cmd == "dam":
        e = need_emp()
        if not e:
            return
        d = S.parse_date(a[1] if len(a) > 1 else "bugun", today)
        if not d:
            return reply("Format: /dam 5 bugun yoki /dam 5 25.10.2026")
        S.set_att(d, e, status="off")
        dm(e, f"ℹ️ {ism(e)}, {S.fmt_day(d)} siz uchun dam olish kuni deb belgilandi.")
        return reply(f"✅ {esc(e.name)}: {S.fmt_day(d)} dam kuni.")
    if cmd == "tatil":
        if len(a) < 2:
            return reply(
                "Format: /tatil 5 25.10.2026 30.10.2026 sabab\n(bir kunlik: /tatil 5 bugun kasal)"
            )
        e = need_emp()
        if not e:
            return
        d_from = S.parse_date(a[1], today)
        if not d_from:
            return reply(f"Sana noto'g'ri: {esc(a[1])}")
        d_to, rest = d_from, a[2:]
        if rest and S.parse_date(rest[0], today):
            d_to, rest = S.parse_date(rest[0], today), rest[1:]
        reason = " ".join(rest) or "ta'til"
        lv = S.add_leave(e, d_from, d_to, reason)
        dm(
            e,
            f"ℹ️ {ism(e)}, sizga {lv.date_from} — {lv.date_to} kunlari belgilandi: {esc(reason)}.",
        )
        return reply(
            f"✅ {esc(e.name)}: {lv.date_from} — {lv.date_to} ({esc(reason)}), #{lv.number}"
        )
    if cmd == "tatillar":
        lv = list(Leave.objects.filter(date_to__gte=today).select_related("employee"))
        if not lv:
            return reply("Faol ta'tillar yo'q.")
        return reply(
            "<b>🏖 Ta'tillar</b>\n"
            + "\n".join(
                f"#{x.number} {esc(x.employee.name)}: {x.date_from} — {x.date_to} ({esc(x.reason)})"
                for x in lv
            )
        )
    if cmd == "tatil_ochir":
        n = re.sub(r"\D", "", a[0]) if a else ""
        deleted = Leave.objects.filter(number=int(n)).delete()[0] if n else 0
        return reply("✅ O'chirildi." if deleted else "Topilmadi.")
    if cmd == "bayram":
        d = S.parse_date(a[0], today) if a else None
        if not d:
            return reply("Format: /bayram 01.01.2027 Yangi yil")
        name = " ".join(a[1:]) or "bayram"
        Holiday.objects.update_or_create(day=d, defaults={"name": name[:128]})
        return reply(f"🎉 {d} — {esc(name)} dam kuni sifatida belgilandi.")
    if cmd == "bayramlar":
        hs = Holiday.objects.filter(day__gte=today)
        return reply(
            "<b>🎉 Bayramlar</b>\n" + ("\n".join(f"{h.day} — {esc(h.name)}" for h in hs) or "Yo'q")
        )
    if cmd == "bayram_ochir":
        d = S.parse_date(a[0], today) if a else None
        n = Holiday.objects.filter(day=d).delete()[0] if d else 0
        return reply("✅ O'chirildi." if n else "Topilmadi.")
    if cmd in ("dchiqar", "dqayta"):
        e = need_emp()
        if not e:
            return
        e.is_active = cmd == "dqayta"
        e.save(update_fields=["is_active"])
        return reply(
            f"✅ {esc(e.name)}"
            + (
                " qayta faollashtirildi."
                if e.is_active
                else " ro'yxatdan chiqarildi (tarix saqlanadi)."
            )
        )
    if cmd == "dsozlamalar":
        L = ["<b>⚙️ Sozlamalar</b>", ""]
        for k, v in S.all_settings().items():
            if k == "OFF_DAYS":
                v = (
                    S.days_label(S.parse_days(v))
                    if S.parse_days(v)
                    else "yo'q (har xodimning o'zi)"
                )
            L.append(f"• {S.label(k)}: <b>{esc(v)}</b>  <code>{k}</code>")
        L += ["", "O'zgartirish: <code>/dsozla REPORT_TIME 11:30</code>"]
        return reply("\n".join(L))
    if cmd in ("vaqt", "kechikish", "dsozla"):
        if cmd == "vaqt" and not a:
            return reply(f"Ish boshlanishi: {S.hm_str(S.start_min())}. O'zgartirish: /vaqt 09:00")
        if cmd == "kechikish" and not a:
            return reply(f"Hozir {S.setting('GRACE_MIN')} daqiqa. O'zgartirish: /kechikish 15")
        key = {"vaqt": "WORK_START", "kechikish": "GRACE_MIN"}.get(cmd) or (
            a[0].upper() if a else ""
        )
        val = " ".join(a if cmd != "dsozla" else a[1:])
        if key not in DEFAULTS or not val:
            return reply("Format: /dsozla KALIT qiymat. Kalitlar: /dsozlamalar")
        from core.exceptions import ServiceError

        try:
            stored = S.set_setting(key, val)
        except ServiceError as err:
            return reply("❌ " + esc(err.message))
        return reply(f"✅ {S.label(key)}: <b>{esc(stored)}</b>")
    if cmd == "guruhlar":
        gs = S.groups()
        return reply(
            f"<b>🏢 Kuzatilayotgan guruhlar ({len(gs)})</b>\n"
            + (
                "\n".join(f"• {esc(g.title)}" for g in gs)
                or "Yo'q. Botni guruhga qo'shib, o'sha yerda /ulash yozing."
            )
        )
    if cmd == "davomat":
        return admin_menu(uid)
    if cmd == "dtozala":
        tm = today + timedelta(days=1)
        return reply(
            "⚠️ <b>Hisobni noldan boshlash</b>\n\nHamma keldi-ketdi yozuvlari, ballar va qo'shimcha ballar o'chiriladi. "
            "Xodimlar ro'yxati, ish vaqtlari, dam kunlari, bayramlar va sozlamalar saqlanib qoladi.\n\nHisob qachondan boshlansin?",
            kb(
                [
                    [(f"📅 Ertadan ({S.fmt_day(tm)})", f"rst:{tm.isoformat()}")],
                    [("📅 Bugundan", f"rst:{today.isoformat()}")],
                    [("❌ Bekor qilish", "rst:no")],
                ]
            ),
        )
    if cmd == "ishvaqti":
        if not a:
            return reply(IV_TITLE, emp_picker_kb(0, "iv"))
        e = need_emp()
        if not e:
            return
        if len(a) > 1 and a[1].lower() == "umumiy":
            set_hours(e, None, None)
            return reply(f"✅ {esc(e.name)}: umumiy vaqt {S.emp_hours(e)}")
        t1, t2 = (a[1] if len(a) > 1 else None), (a[2] if len(a) > 2 else None)
        if t1 and not t2 and re.fullmatch(r"\d{1,2}(:\d\d)?-\d{1,2}(:\d\d)?", t1):
            t1, t2 = t1.split("-")

        def fix(t):
            return f"{t}:00" if t and re.fullmatch(r"\d{1,2}", t) else t

        s1, s2 = S.parse_hm(fix(t1)), S.parse_hm(fix(t2))
        if s1 is None or s2 is None or s2 <= s1:
            return reply(
                "Format: /ishvaqti 5 10:00 19:00 (yoki /ishvaqti 5 10-19, /ishvaqti 5 umumiy)"
            )
        set_hours(e, S.hm_str(s1), S.hm_str(s2))
        return reply(f"✅ {esc(e.name)}: ish vaqti {S.emp_hours(e)}")
    if cmd == "ball":
        e = need_emp()
        if not e:
            return
        try:
            v = int(str(a[1] if len(a) > 1 else "").replace("−", "-"))
        except ValueError:
            v = 0
        if not v or abs(v) > 100:
            return reply("Format: /ball 5 +10 sabab (yoki /ball 5 -5 sabab), ko'pi bilan 100")
        why = " ".join(a[2:])
        S.add_points(e, v, why, today)
        dm(
            e,
            (
                (
                    f"🌟 {ism(e)}, rahbar sizga <b>+{v} ball</b> berdi"
                    + (f": {esc(why)}" if why else "")
                    + ". Barakalla, shunday davom eting! 👏"
                )
                if v > 0
                else (
                    f"ℹ️ {ism(e)}, sizga <b>{v} ball</b> yozildi"
                    + (f": {esc(why)}" if why else "")
                    + ". Keyingi safar albatta yaxshiroq bo'ladi, ishonamiz. 🙏"
                )
            ),
        )
        return reply(f"✅ {esc(e.name)}: {v:+d} ball" + (f" ({esc(why)})" if why else ""))
    if cmd == "reyting":
        if a and re.fullmatch(r"yil|\d{4}", a[0], re.I):
            y = a[0] if a[0].isdigit() else str(today.year)
            return reply(R.year_report(y, now_d)[0])
        ym = a[0] if a and re.fullmatch(r"\d{4}-\d{2}", a[0]) else today.strftime("%Y-%m")
        return reply(R.ranking_text(S.month_stats(ym, now_d), f"🏆 Reyting — {S.month_name(ym)}"))
    return reply("Noma'lum buyruq. /dyordam")


def set_hours(e: Employee, ws, we):
    S.set_hours(e, ws, we)
    dm(
        e,
        f"ℹ️ {ism(e)}, ish vaqtingiz belgilandi: <b>{S.emp_hours(e)}</b>. "
        f"<b>{S.hm_str(S.emp_start(e) + S.setting_int('GRACE_MIN'))}</b> gacha kelsangiz vaqtida hisoblanadi. Kelganda va ketayotganda guruhga video-doiracha tashlang. 🙂",
    )


def emp_picker_kb(page: int, mode: str = ""):
    iv = mode == "iv"
    emps = S.active_emps()
    per = 30
    sl = emps[page * per : page * per + per]
    rows = []
    for i in range(0, len(sl), 2):
        row = []
        for e in sl[i : i + 2]:
            if iv:
                row.append(
                    (
                        f"{e.name} ({S.emp_hours(e)}{'' if e.work_start else '*'})",
                        f"iv:{e.telegram_id}",
                    )
                )
            else:
                off = S.emp_off_days(e)
                row.append(
                    (
                        e.name + (f" ({','.join(WD_SHORT[d - 1] for d in off)})" if off else " ⚠️"),
                        f"dk:{e.telegram_id}",
                    )
                )
        rows.append(row)
    pk = "ivp:" if iv else "dkp:"
    nav = []
    if page > 0:
        nav.append(("⬅️", f"{pk}{page - 1}"))
    if len(emps) > (page + 1) * per:
        nav.append(("➡️", f"{pk}{page + 1}"))
    if nav:
        rows.append(nav)
    return kb(rows)


def iv_kb(e: Employee):
    rows = []
    for ws, we in IV_PRESETS:
        cur = e.work_start == ws and e.work_end == we
        rows.append(
            [
                (
                    ("✅ " if cur else "") + f"{ws} – {we}",
                    f"ivs:{e.telegram_id}:{ws.replace(':', '')}-{we.replace(':', '')}",
                )
            ]
        )
    rows.append(
        [
            (
                f"Umumiy vaqt ({S.hm_str(S.start_min())} – {S.hm_str(S.end_min())})",
                f"ivs:{e.telegram_id}:0",
            )
        ]
    )
    rows.append([("⬅️ Ro'yxatga qaytish", "ivp:0")])
    return kb(rows)


def off_days_kb(e: Employee):
    off = e.off_days or []
    r1 = [
        (("✅ " if d in off else "") + WD_SHORT[d - 1], f"dkt:{e.telegram_id}:{d}")
        for d in range(1, 5)
    ]
    r2 = [
        (("✅ " if d in off else "") + WD_SHORT[d - 1], f"dkt:{e.telegram_id}:{d}")
        for d in range(5, 8)
    ]
    return kb(
        [r1, r2, [("✔️ Tayyor", f"dkd:{e.telegram_id}")], [("⬅️ Ro'yxatga qaytish", "dkp:0")]]
    )


def admin_callback(q: dict, p: list[str], ans):
    chat_id, mid = q["message"]["chat"]["id"], q["message"]["message_id"]

    def edit(text, k=None):
        api.call(
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": mid,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": k or {"inline_keyboard": []},
            },
        )

    kind, uid = p[0], q["from"]["id"]
    if kind == "m":
        ans()
        if p[1] == "off":
            return edit("Kimning dam kunlarini belgilaymiz?", emp_picker_kb(0))
        if p[1] == "iv":
            return edit(IV_TITLE, emp_picker_kb(0, "iv"))
        cmd = {
            "today": "dhisobot",
            "month": "doy",
            "emps": "dxodimlar",
            "hol": "bayramlar",
            "set": "dsozlamalar",
            "sheet": "djadval",
            "help": "dyordam",
            "rank": "reyting",
        }.get(p[1])
        if cmd:
            admin_command(cmd, [], uid)
        return
    if kind == "hol":
        hol_day = date.fromisoformat(p[1])
        ans()
        if HolidayDecision.objects.filter(holiday_day=hol_day).exists():
            return edit("Bu bayram bo'yicha qaror allaqachon qabul qilingan.")
        name = S.holiday_name(hol_day)
        if p[2] == "x":
            S.set_state(f"AWAIT_{uid}", f"hol:{hol_day.isoformat()}")
            return edit(
                f"🎉 {S.fmt_day(hol_day)} — {esc(name)}.\nNecha kun dam olinadi? Son yozing. "
                "Boshqa sanadan boshlansa, sanasini ham yozing, masalan: <code>3 20.03</code>"
            )
        n = int(p[2])
        edit(f"🎉 {S.fmt_day(hol_day)} — {esc(name)}: " + (f"{n} kun dam." if n else "ishlaymiz."))
        return announce_holiday(hol_day, n, hol_day)
    if kind == "dkp":
        ans()
        return edit("Kimning dam kunlarini belgilaymiz?", emp_picker_kb(int(p[1])))
    if kind == "rst":
        ans()
        if p[1] == "no":
            return edit("Bekor qilindi. Hech narsa o'chirilmadi.")
        d = date.fromisoformat(p[1])
        S.reset_data(d)
        return edit(
            f"✅ Tozalandi. Hisob <b>{S.fmt_day(d)}</b> dan boshlanadi.\nKeldi-ketdi, ballar va reyting shu kundan yangidan yoziladi."
        )
    if kind == "ivp":
        ans()
        return edit(IV_TITLE, emp_picker_kb(int(p[1]), "iv"))
    if kind == "ann":
        ans()
        return announce_winner(p[1], p[2], int(p[3]), edit)
    if kind in ("iv", "ivs"):
        ee = S.emp(p[1])
        if not ee:
            return ans("Xodim topilmadi")
        if kind == "iv":
            ans()
            return edit(f"🕐 <b>{esc(ee.name)}</b> ish vaqti (hozir {S.emp_hours(ee)}):", iv_kb(ee))
        if p[2] == "0":
            set_hours(ee, None, None)
        else:
            t1, t2 = p[2].split("-")
            set_hours(ee, f"{t1[:2]}:{t1[2:]}", f"{t2[:2]}:{t2[2:]}")
        ans("Saqlandi")
        return edit(
            f"✅ <b>{esc(ee.name)}</b>: {S.emp_hours(ee)}\n\n{IV_TITLE}", emp_picker_kb(0, "iv")
        )
    if kind in ("offok", "offno"):
        day, e = date.fromisoformat(p[1]), S.emp(p[2])
        if not e:
            return ans("Xodim topilmadi")
        ans()
        if kind == "offok":
            S.set_att(day, e, status="off", off_requested=False)
            edit(f"✅ {esc(e.name)}: {S.fmt_day(day)} dam kuni deb tasdiqlandi.")
            dm(
                e,
                f"✅ {ism(e)}, rahbar tasdiqladi: bugun dam olish kuningiz. Yaxshi dam oling, kuch to'plang! 😊",
            )
        else:
            S.set_att(day, e, off_requested=False)
            edit(f"❌ {esc(e.name)}: dam kuni rad etildi.")
            dm(
                e,
                f"{ism(e)}, afsuski rahbar bugungi dam kunini tasdiqlamadi. Iltimos, ishga keling va guruhga video-doiracha tashlang. Tushunganingiz uchun rahmat! 🙏",
            )
        return
    e = S.emp(p[1])
    if not e:
        return ans("Xodim topilmadi")
    if kind == "dk":
        ans()
        return edit(
            f"<b>{esc(e.name)}</b> dam kunlarini belgilang (bir nechta tanlash mumkin):",
            off_days_kb(e),
        )
    if kind == "dkt":
        d = int(p[2])
        off = list(e.off_days or [])
        was = d in off
        off = sorted([x for x in off if x != d] if was else off + [d])
        e.off_days = off
        e.save(update_fields=["off_days"])
        ans(WD_SHORT[d - 1] + (" olib tashlandi" if was else " qo'shildi"))
        return edit(
            f"<b>{esc(e.name)}</b> dam kunlarini belgilang (bir nechta tanlash mumkin):",
            off_days_kb(e),
        )
    if kind == "dkd":
        ans("Saqlandi")
        dm(
            e,
            f"ℹ️ {ism(e)}, sizning dam olish kunlaringiz: <b>{S.days_label(e.off_days or [])}</b>",
        )
        return edit(
            f"✅ <b>{esc(e.name)}</b> dam kunlari: {S.days_label(e.off_days or [])}",
            emp_picker_kb(0),
        )


def announce_holiday(hol_day: date, n: int, start: date):
    name = S.holiday_name(hol_day)
    days = S.apply_holiday(hol_day, n, start)
    if not n:
        return notify_admins(f"✅ {S.fmt_day(hol_day)} ({esc(name)}) — ish kuni, dam olinmaydi.")
    txt = S.fmt_day(days[0]) if len(days) == 1 else f"{S.fmt_day(days[0])} — {S.fmt_day(days[-1])}"
    notify_admins(
        f"✅ Dam olish belgilandi: <b>{txt}</b> ({n} kun). Bu kunlarda xodimlardan otchet so'ralmaydi."
    )
    for g in S.groups():
        send(
            g.chat_id,
            f"🎉 Hurmatli jamoa! {esc(name)} munosabati bilan <b>{txt}</b> dam olish kunlari. Bayramingiz muborak bo'lsin! 🎊",
        )


def announce_winner(kind: str, period: str, tg_id: int, edit=None) -> str:
    """announceWinner_: post «Oy/Yil xodimi» in every group (once per period)."""
    if Winner.objects.filter(kind=kind, period=period).exists():
        msg = "Bu tanlov allaqachon e'lon qilingan."
        if edit:
            edit(msg)
        return msg
    e = S.emp(tg_id)
    if not e:
        msg = "Xodim topilmadi."
        if edit:
            edit(msg)
        return msg
    now_d = S.now()
    if kind == "m":
        st = next((s for s in S.month_stats(period, now_d) if s.e.id == e.id), None)
        pts, disc = (st.pts, st.disc) if st else (0, 0)
    else:
        st = next((s for s in S.year_stats(period, now_d) if s["e"].id == e.id), None)
        pts, disc = (st["pts"], st["disc"]) if st else (0, 0)
    Winner.objects.create(kind=kind, period=period, employee=e)
    what = (
        f"🏆 <b>{S.month_name(period)} oyining eng yaxshi xodimi</b>"
        if kind == "m"
        else f"👑 <b>{period}-yilning eng yaxshi xodimi</b>"
    )
    t = (
        f"🎉 Hurmatli jamoa!\n\n{what} — <b>{esc(e.name)}</b>! 👏\n⭐ {pts} ball · intizom {disc}%\n\n"
        + random.choice(TXT["winner"])
        + "\n\nKeyingi g'olib siz bo'lishingiz mumkin! 💪"
    )
    gs = S.groups()
    for g in gs:
        send(g.chat_id, t)
    dm(
        e,
        f"🎉 {ism(e)}, tabriklaymiz! Siz "
        + (f"{S.month_name(period)} oyining" if kind == "m" else f"{period}-yilning")
        + " eng yaxshi xodimi deb topildingiz! 🏆\nIntizomingiz va mehnatingiz uchun katta rahmat. Jamoamiz siz bilan faxrlanadi! 🙏",
    )
    msg = f"✅ {esc(e.name)} — {'oy' if kind == 'm' else 'yil'} xodimi sifatida {len(gs)} ta guruhda e'lon qilindi."
    if edit:
        edit(msg)
    return msg
