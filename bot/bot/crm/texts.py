"""All strings of the CRM bot part (Uzbek). `callback_data` strings live in keyboards.py
and must stay stable."""

from __future__ import annotations

from bot.common.fmt import esc

NEW_BTN = "🆕 Yangi mijoz"

# keys = contract (docs/BOT_CONTRACT.md: LeadSource), labels = backend's Uzbek labels
SOURCES: dict[str, str] = {
    "telegram": "Telegram",
    "instagram": "Instagram",
    "phone": "Telefon qo'ng'iroq",
    "showroom": "Do'konga keldi (showroom)",
    "recommendation": "Tavsiya",
    "other": "Boshqa",
}

START_HINT = (
    "🆕 Yangi mijoz qo'shish: «" + NEW_BTN + "» tugmasi yoki /mijoz. "
    "Mijoz xabarini shu yerga forward qilsangiz ham bo'ladi."
)
FIN_HINT = "Yangi mijoz: /mijoz"
DUPLICATE = "ℹ️ Bu ariza allaqachon yaratilgan edi"

ASK_NAME = "👤 <b>Yangi mijoz</b>\n\nMijoz ismini yozing:"
ASK_PHONE = "📞 Telefon raqamini yozing (masalan, +998901234567) yoki kontakt yuboring:"
ASK_SOURCE = "📣 Mijoz qayerdan keldi?"
ASK_NOTE = "📝 Izoh yozing (mijoz nima so'radi?):"
ASK_REMIND = "⏰ Qachon eslatib qo'yaylik?"
ASK_REMIND_CUSTOM = (
    "⏰ Vaqtni yozing: <code>15:30</code> (bugun), <code>05.11</code> yoki "
    "<code>05.11 14:00</code>."
)
CANCELLED = "Bekor qilindi."
STALE = "Bu tugma eskirgan."
ALREADY_SAVED = "Allaqachon saqlandi"
ALREADY_DONE = "Allaqachon bajarilgan"
USE_BUTTONS = "Iltimos, yuqoridagi tugmalardan birini tanlang."
SAVING = "⏳ Saqlanmoqda…"
OPEN_PANEL = "💻 Panelda ochish"
MAP_BTN = "🗺 Yandex xaritada"

LOC_ASK = "📍 Lokatsiya olindi.\n\nQaysi mijoz? Telefon raqamini yozing yoki ro'yxatdan tanlang:"
LOC_ASK_EMPTY = (
    "📍 Lokatsiya olindi.\n\nSizga tegishli ochiq ariza yoki o'lchov topilmadi. "
    "Mijozning telefon raqamini yozing:"
)
LOC_PHONE_NONE = "Bu raqam bo'yicha ochiq ariza yoki o'lchov topilmadi."
LOC_IN_LEAD = "📍 Lokatsiya arizaga biriktiriladi. Davom eting."
LOC_LIVE = "ℹ️ Jonli lokatsiya: hozirgi nuqta saqlanadi."
# a location the bot could not take: say why instead of staying silent
LOC_NOT_LINKED = (
    "📍 Lokatsiyani saqlab bo'lmadi: Telegram'ingiz saytdagi profilingizga ulanmagan.\n"
    "Saytda menyu pastidagi «Telegramni ulash» tugmasini bosing, so'ng lokatsiyani qayta yuboring."
)
LOC_NO_RIGHT = (
    "📍 Lokatsiyani saqlash uchun arizalar yoki o'lchovlarni o'zgartirish huquqi kerak. "
    "Administratorga murojaat qiling."
)
LOC_BUSY = (
    "📍 Hozir boshqa amal ochiq. Uni tugating yoki /bekor ni bosing, "
    "so'ng lokatsiyani qayta yuboring."
)
LOC_SAME = "ℹ️ Xuddi shu nuqta avvaldan bor edi."


def dt_short(iso: str | None) -> str:
    """'2026-11-05T10:00:00' -> '05.11 10:00'."""
    s = str(iso or "")
    if len(s) >= 16 and s[4] == "-":
        return f"{s[8:10]}.{s[5:7]} {s[11:16]}"
    return s or "—"


def remind_label(remind: dict | None) -> str:
    r = remind or {}
    if r.get("at"):
        return dt_short(str(r["at"]))
    return {"today": "Bugun", "tomorrow": "Ertaga 10:00"}.get(r.get("preset"), "Eslatmasiz")


def known_client(info: dict) -> str:
    """The «Bazada bor» line of the phone step (answer of GET crm/clients/)."""
    line = f"ℹ️ Bazada bor: <b>{esc(info.get('fio'))}</b>, {int(info.get('invoices_count') or 0)} ta ariza"
    inv = info.get("open_invoice")
    if inv:
        who = (inv.get("assigned") or {}).get("name")
        line += f"; ochiq ariza #{inv.get('id')}" + (f" ({esc(who)})" if who else "")
    return line


def summary(d: dict) -> str:
    rows = [
        "📋 <b>Tekshiring</b>",
        "",
        f"👤 {esc(d.get('name'))}",
        f"📞 {esc(d.get('phone'))}",
        f"📣 {esc(SOURCES.get(d.get('source') or '', d.get('source') or '—'))}",
        f"📝 {esc(d.get('note')) or '—'}",
        f"⏰ {esc(remind_label(d.get('remind')))}",
    ]
    if d.get("location"):
        rows.append("📍 Lokatsiya bor")
    return "\n".join(rows)


def saved(res: dict) -> str:
    inv = res.get("invoice") or {}
    cl = inv.get("client") or {}
    rows = [f"✅ Ariza #{inv.get('id')} yaratildi", ""]
    rows.append(f"👤 {esc(cl.get('fio'))} · {esc(cl.get('phone'))}")
    if inv.get("source_label"):
        rows.append(f"📣 {esc(inv['source_label'])}")
    if (inv.get("assigned") or {}).get("name"):
        rows.append(f"🧑‍💼 {esc(inv['assigned']['name'])}")
    task = res.get("task")
    if task:
        rows.append(f"⏰ {esc(dt_short(task.get('due_at')))} — {esc(task.get('text'))}")
    if res.get("client_existed"):
        rows.append("ℹ️ Mijoz bazada avvaldan bor edi.")
    return "\n".join(rows)


def task_due(d: dict) -> str:
    t = d["task"]
    inv = d.get("invoice") or {}
    cl = inv.get("client") or {}
    rows = ["⏰ <b>Vazifa vaqti keldi</b>", ""]
    rows.append(f"👤 {esc(cl.get('fio'))} · {esc(cl.get('phone'))}")
    rows.append(f"✔️ {esc(t.get('text'))}")
    rows.append(f"🕒 {esc(dt_short(t.get('due_at')))}")
    if inv.get("source_label"):
        rows.append(f"📣 {esc(inv['source_label'])}")
    if inv.get("last_note"):
        rows.append("")
        rows.append(f"📝 {esc(inv['last_note'])}")
    return "\n".join(rows)


def loc_button(it: dict) -> str:
    """Button label of a location candidate (GET crm/locations/candidates/ item)."""
    cl = it.get("client") or {}
    mark = " ✅" if it.get("has_point") else ""
    if it.get("kind") == "invoice":
        return f"📋 #{it.get('id')} {cl.get('fio') or ''}{mark}"
    return f"📐 {dt_short(it.get('when'))} {cl.get('fio') or ''}{mark}"


def loc_saved(res: dict) -> str:
    t = res.get("target") or {}
    cl = t.get("client") or {}
    what = "ariza" if t.get("kind") == "invoice" else "o'lchov"
    line = f"✅ Lokatsiya saqlandi: {what} #{t.get('id')} — {esc(cl.get('fio'))} · {esc(cl.get('phone'))}"
    names = {"metering": "o'lchovga", "order": "buyurtmaga"}
    filled = []
    for f in res.get("filled") or []:
        n = names.get(f.get("kind"))
        if n and n not in filled:
            filled.append(n)
    if filled:
        line += f"\n({' va '.join(filled)} ham qo'shildi)"
    if res.get("changed") is False:
        line += "\n" + LOC_SAME
    return line
