"""Inline keyboards of the CRM part. callback_data (stable): crm:name:use|client,
crm:phone:use, crm:src:{key}, crm:note:skip, crm:rem:today|tomorrow|custom|none,
crm:save, crm:cancel, crm:done:{task}, crm:sn:1h|tm:{task}."""

from __future__ import annotations

from bot.common.kb import b, grid, ik, reply_kb, url_button

from .texts import NEW_BTN, OPEN_PANEL, SOURCES

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


def task_kb(task_id: int, url: str = ""):
    rows = []
    if url:
        rows.append([url_button(OPEN_PANEL, url)])
    rows.append([b("✅ Bajarildi", f"crm:done:{task_id}")])
    rows.append([b("⏰ +1 soat", f"crm:sn:1h:{task_id}"), b("🌅 Ertaga", f"crm:sn:tm:{task_id}")])
    return ik(rows)
