"""Inline keyboards of the CRM part. callback_data (stable): crm:name:use|client,
crm:phone:use, crm:src:{key}, crm:note:skip, crm:rem:today|tomorrow|custom|none,
crm:save, crm:cancel, crm:done:{task}, crm:sn:1h|tm:{task},
crm:loc:i:{invoice_id}, crm:loc:m:{metering_id}, crm:loc:new, crm:loc:x."""

from __future__ import annotations

from bot.common.kb import b, grid, ik, reply_kb, url_button

from . import texts as T
from .texts import MAP_BTN, NEW_BTN, OPEN_PANEL, SOURCES

CANCEL = b("❌ Bekor qilish", "crm:cancel")


def menu_kb():
    """Persistent reply keyboard of a lead-adder who has no other menu."""
    return reply_kb([[NEW_BTN]])


def name_kb(prefill: str = ""):
    rows = [[b(f"✅ {prefill}"[:60], "crm:name:use")]] if prefill else []
    return ik(rows + [[CANCEL]])


def phone_kb(prefill: str = ""):
    rows = [[b(f"📞 {prefill}", "crm:phone:use")]] if prefill else []
    return ik(rows + [[CANCEL]])


def source_kb(selected: str = "", client_fio: str = ""):
    rows = []
    if client_fio:
        rows.append([b(f"👤 Shu ismni olish: {client_fio}"[:60], "crm:name:client")])
    btns = [
        b(("✅ " if k == selected else "") + label, f"crm:src:{k}") for k, label in SOURCES.items()
    ]
    return ik(rows + grid(btns, 2) + [[CANCEL]])


def note_kb(has_prefill: bool = False):
    return ik(
        [
            [b("➡️ Davom etish" if has_prefill else "➡️ O'tkazib yuborish", "crm:note:skip")],
            [CANCEL],
        ]
    )


def remind_kb():
    return ik(
        [
            [b("Bugun", "crm:rem:today"), b("Ertaga", "crm:rem:tomorrow")],
            [b("🕒 Vaqtni yozaman", "crm:rem:custom"), b("Eslatmasiz", "crm:rem:none")],
            [CANCEL],
        ]
    )


def confirm_kb():
    return ik([[b("✅ Saqlash", "crm:save")], [CANCEL]])


def cancel_kb():
    return ik([[CANCEL]])


def panel_kb(url: str):
    return ik([[url_button(OPEN_PANEL, url)]]) if url else None


def task_kb(task_id: int, url: str = "", map_url: str = ""):
    rows = []
    if url:
        rows.append([url_button(OPEN_PANEL, url)])
    if map_url:
        rows.append([url_button(MAP_BTN, map_url)])
    rows.append([b("✅ Bajarildi", f"crm:done:{task_id}")])
    rows.append([b("⏰ +1 soat", f"crm:sn:1h:{task_id}"), b("🌅 Ertaga", f"crm:sn:tm:{task_id}")])
    return ik(rows)


def loc_targets_kb(items: list[dict], can_new_lead: bool = False):
    """One button per candidate (invoice `crm:loc:i:{id}`, metering `crm:loc:m:{id}`),
    then «🆕 Yangi mijoz» (`crm:loc:new`) and cancel (`crm:loc:x`)."""
    rows = []
    for it in items:
        code = "i" if it.get("kind") == "invoice" else "m"
        rows.append([b(T.loc_button(it)[:60], f"crm:loc:{code}:{it.get('id')}")])
    if can_new_lead:
        rows.append([b(NEW_BTN, "crm:loc:new")])
    rows.append([b("❌ Bekor qilish", "crm:loc:x")])
    return ik(rows)


def loc_done_kb(map_url: str = "", url: str = ""):
    rows = []
    if map_url:
        rows.append([url_button(MAP_BTN, map_url)])
    if url:
        rows.append([url_button(OPEN_PANEL, url)])
    return ik(rows) if rows else None
