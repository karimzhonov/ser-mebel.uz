"""Texts the davomat bot says to employees (private chat), built from backend answers.

Wording is copied from the old backend/hr/telegram.py; the backend now only says WHAT
happened (kinds + data) and the bot picks the words.
"""

from __future__ import annotations

import random

from . import keyboards as K
from .fmt import esc, fmt_min, ism
from .texts import ST_LABEL, TXT

ETA_OK = "Tushunarli, {ism}. Soat {eta} ga kutamiz. Yetib kelishingiz bilan guruhga video-doiracha tashlashni unutmang! 👍"
REASON_ACK = (
    "Rahmat, {ism}, oldindan xabar berganingiz yaxshi bo'ldi. "
    "Rahbaringizga yetkazdim. Tezroq hammasi joyiga tushsin! 🙏"
)


# ------------------------------------------------------------------ group report -> DM
def group_dm(dm: dict):
    """hr/group-message/ `dm` -> (text, keyboard|None) for the employee's private chat."""
    kind = dm["kind"]
    e = dm["employee"]
    name = ism(e["name"])
    at = dm.get("at", "")
    day = dm.get("day", "")
    if kind == "checkin_on_time":
        t = (
            f"Xayrli tong, {name}! ☀️\nOtchetingiz qabul qilindi, kelgan vaqtingiz: <b>{at}</b>.\n"
            + random.choice(TXT["praise"])
        )
        if dm.get("uniform_ask"):
            return t + "\n\n👕 Bugun formadamisiz?", K.uniform_kb(day)
        return t, None
    if kind == "checkin_late":
        return (
            f"{name}, otchetingiz qabul qilindi, kelgan vaqtingiz: <b>{at}</b>.\n"
            f"⏰ Bugun <b>{fmt_min(dm.get('late_min'))}</b> kechikib keldingiz.\n\n"
            "Hammasi joyidami? Kechikishga uzrli sabab bo'ldimi?",
            K.late_reason_kb(day),
        )
    if kind == "checkout":
        return (
            f"Rahmat, {name}! 🙏 Ketish vaqtingiz qayd etildi: <b>{at}</b>.\n"
            + random.choice(TXT["bye"]),
            None,
        )
    if kind == "checkout_early":
        return (
            f"{name}, ketish vaqtingiz qayd etildi: <b>{at}</b>.\n🚪 Ish vaqtingiz "
            f"<b>{dm.get('end', '')}</b> gacha edi, ya'ni <b>{fmt_min(dm.get('early_min'))}</b> "
            "erta ketyapsiz.\n\nRahbar bilan kelishilganmi yoki uzrli sabab bormi?",
            K.early_reason_kb(day),
        )
    if kind == "leave_without_checkin":
        return (
            f"Rahmat, {name}! Ketish vaqtingiz qayd etildi: <b>{at}</b>.\n"
            "Lekin bugun ertalab kelish otchetingizni ko'rmadim. 🤔 Iltimos, ertaga ishga "
            "kelganingizda ham guruhga <b>video-doiracha</b> tashlang. Yaxshi dam oling! 🌙",
            None,
        )
    if kind == "format_warning":
        return (
            f"{name}, otchetingizni ko'rdim, rahmat! 🙂 Faqat bitta iltimos: otchet "
            "<b>video-doiracha</b> (dumaloq video) ko'rinishida bo'lishi kerak. "
            "Guruhga qaytadan dumaloq video tashlab yuboring (Telegramda mikrofon tugmasini "
            "bir marta bossangiz, kamera belgisiga o'tadi).",
            None,
        )
    raise ValueError(f"unknown dm kind {kind!r}")


def group_reply(reply: dict) -> str:
    """GROUP_ACK == reply: the text under the report in the group."""
    if reply["status"] == "on_time":
        return f"✅ Qabul qilindi, {reply['at']} — vaqtida"
    return f"⏰ Qabul qilindi, {reply['at']} — {fmt_min(reply.get('late_min'))} kechikish"


def welcome_member(name: str) -> str:
    return (
        f"Xush kelibsiz, {esc(name)}! 👋\nHar kuni ishga kelganingizda shu guruhga "
        "<b>video-doiracha</b> otchet tashlang.\nEslatmalarni olish uchun botga ulaning 👇"
    )


GROUP_CONNECTED = (
    "Hurmatli xodimlar! Har kuni ishga kelganingizda shu guruhga <b>video-doiracha</b> otchet "
    "tashlang. Eslatmalarni olish uchun botga ulaning 👇"
)
NOT_ADMIN_WARN = "\n\n⚠️ Bot barcha xabarlarni ko'rishi uchun uni guruhda <b>admin</b> qiling."


# ------------------------------------------------------------------ employee buttons
def callback_reply(kind: str, data: dict, day: str):
    """hr/callback/ `reply` -> (text, keyboard|None)."""
    e = data.get("employee") or {}
    n = ism(e.get("name"))
    if kind == "uniform_yes":
        return f"Zo'r, {n}! Toza va tartibli ko'rinish - professionallik belgisi. 👍", None
    if kind == "uniform_no":
        return (
            f"{n}, iltimos, formani unutmang. Ertaga albatta forma bilan keling, bu jamoamiz "
            "qiyofasi uchun muhim. 🙏",
            None,
        )
    if kind == "late_reason_ask":
        if data.get("reason") == "Sababli":
            return f"Tushunarli, {n}. Sababini qisqacha yozib yuboring:", None
        return (
            f"Tushunarli, {n}. Ochiq javobingiz uchun rahmat. Qisqacha yozing: nima sabab "
            "bo'ldi va keyingi safar buning oldini qanday olasiz?",
            None,
        )
    if kind == "early_reason_ask":
        if data.get("reason") == "Sababli":
            return (
                f"Tushunarli, {n}. Qisqacha yozib yuboring: sababi nima yoki kim bilan "
                "kelishilgan?",
                None,
            )
        return (
            f"Tushunarli, {n}. Ochiq javobingiz uchun rahmat. Qisqacha izoh yozing: nima uchun "
            "erta ketishga to'g'ri keldi?",
            None,
        )
    if kind == "eta_ok":
        return ETA_OK.format(ism=n, eta=data.get("eta", "")), None
    if kind == "here_ok":
        return (
            f"Ajoyib, {n}! Iltimos, hoziroq ish guruhiga video-doiracha tashlang - vaqt "
            "o'shanda yoziladi. 👍",
            None,
        )
    if kind == "cant_ask":
        return f"Tushunarli, {n}. Iltimos, sababini tanlang yoki yozib yuboring:", K.reason_kb(day)
    if kind == "excused_done":
        return REASON_ACK.format(ism=n), None
    if kind == "reason_other":
        return "Sababni qisqacha yozib yuboring:", None
    if kind == "offreq_sent":
        return (
            f"{n}, so'rovingizni rahbarga yubordim. Javob kelishi bilan shu yerda xabar beraman.",
            None,
        )
    raise ValueError(f"unknown callback reply kind {kind!r}")


# ------------------------------------------------------------------ free-text answers
def private_text_reply(outcome: str, data: dict, name: str, day: str):
    """hr/private-text/ -> list of (text, keyboard|None) to send in order."""
    n = ism(name)
    if outcome == "late_comment":
        t = f"Rahmat, {n}, izohingizni yozib qo'ydim. " + (
            "Tushunganingiz uchun rahmat, ishingizga omad! 🙏"
            if data.get("late_reason") == "Sababli"
            else "Ertaga sizni vaqtida kutamiz, ishonaman, uddalaysiz! 💪"
        )
        out = [(t, None)]
        if data.get("uniform_ask"):
            out.append(("👕 Bugun formadamisiz?", K.uniform_kb(day)))
        return out
    if outcome == "early_comment":
        return [
            (
                f"Rahmat, {n}, izohingizni yozib qo'ydim. "
                + (
                    "Yaxshi dam oling! 🙏"
                    if data.get("early_reason") == "Sababli"
                    else "Ertaga ish kunini oxirigacha birga yakunlaymiz, degan umiddaman. 💪"
                ),
                None,
            )
        ]
    if outcome == "excused":
        return [(REASON_ACK.format(ism=n), None)]
    if outcome == "eta":
        return [(ETA_OK.format(ism=n, eta=data.get("eta", "")), None)]
    return []


# ------------------------------------------------------------------ /start, /holatim
def start_text(e: dict) -> str:
    return (
        f"Assalomu alaykum, {ism(e['name'])}! 👋\nMen SerMebel jamoasining davomat yordamchisiman. "
        "Endi ish vaqti bo'yicha siz bilan shu yerda muloqot qilamiz. ✅\n\n"
        "Qanday ishlaydi:\n• Ishga kelganingizda guruhga <b>video-doiracha</b> tashlang.\n"
        f"• Ish vaqtingiz: <b>{e['hours_label']}</b>. <b>{e['ontime_until']}</b> gacha kelsangiz "
        "vaqtida hisoblanadi.\n"
        "• Ketayotganda ham guruhga <b>video-doiracha</b> tashlang.\n"
        "• Har kuni ball yig'asiz, oy oxirida eng yaxshisi <b>🏆 Oy xodimi</b> bo'ladi. /ballarim\n"
        f"• Kechiksangiz, sababini so'rayman.\n• Kela olmasangiz /kelolmayman yuboring.\n"
        f"• Dam kuningiz: <b>{e['off_label']}</b>\n\n/holatim - holatingiz"
    )


NOT_FOUND_IN_GROUPS = (
    "Assalomu alaykum! Siz ish guruhlarida topilmadingiz. "
    "Avval ish guruhiga qo'shiling, keyin qayta /start bosing."
)
NOT_AN_EMPLOYEE = "Siz xodimlar ro'yxatida yo'qsiz."
NOT_IN_ATTENDANCE_LIST = "Siz davomat ro'yxatida yo'qsiz."
ALREADY_IN = "Siz bugun allaqachon otchet tashlagansiz. 🙂"


def status_text(res: dict) -> str:
    e = res["employee"]
    t = res["today"]
    if t.get("st"):
        today = (
            ST_LABEL.get(t["st"], t["st"])
            + (f", keldi {t['in_time']}" if t.get("in_time") else "")
            + (f", ketdi {t['out_time']}" if t.get("out_time") else "")
        )
    else:
        today = "-"
    L = [
        f"<b>{esc(e['name'])}</b>",
        f"🕐 Ish vaqtingiz: <b>{e['hours_label']}</b>",
        "🗓 Bugun: " + today,
    ]
    m = res.get("month")
    if m:
        L += [
            "",
            "<b>Shu oy:</b>",
            f"⭐ Ball: <b>{m['pts']}</b> · reytingda <b>{m['rank']}-o'rin</b> ({m['of']} kishidan)",
            f"✅ Vaqtida: {m['on_time']} · ⏰ Kech: {m['late']}"
            + (f" (jami {fmt_min(m['late_min'])})" if m["late_min"] else ""),
            f"❌ Kelmadi: {m['absent']} · 📝 Sababli: {m['excused']} · 🚪 Erta ketdi: {m['early_n']}",
            f"📈 Intizom: <b>{m['disc']}%</b>",
            "",
            "Ballar qanday hisoblanadi: /ballar",
        ]
    return "\n".join(L)
