"""Telegram side effects shared by the bot and the site (channel posts, owner/admin
notices). Failures are logged, never raised: a down Telegram must not undo a booking."""

from __future__ import annotations

import logging

from constance import config

from oauth.models import TelegramMember

from .. import services as S
from ..text import esc, money
from ..constants import CAT_ADVANCE, CAT_REST, OpKind
from ..models import Operation
from . import api
from .texts import KB_STAFF, op_card

log = logging.getLogger("finance.notify")


def to_channel(text: str, photo_id: str | None = None):
    ch = str(config.FIN_CHANNEL_ID or "").strip()
    if not ch:
        return
    if photo_id:
        api.send_photo(ch, photo_id, text)
    else:
        api.send(ch, text)


def to_admins(text: str, kb=None, exclude: TelegramMember | None = None):
    for a in S.admins():
        if exclude and a.pk == exclude.pk:
            continue
        api.send(a.telegram_id, text, kb)


def notify_to(members: list[TelegramMember], who: str, text: str, photo=None, kb=None) -> bool:
    """Send to the duty holders; if nobody holds the duty, to the admins with a note
    (notifyTo_). Returns True when it fell back to the admins."""
    fallback = not members
    if fallback:
        members = S.admins()
        text = (
            f"⚠️ <i>{who} belgilanmagan (saytda Moliya → Telegram a'zolar). Xabar sizga keldi:</i>\n\n"
            + text
        )
    for m in members:
        if photo is not None:
            r = api.send_photo(m.telegram_id, photo, text, kb)
            if r.get("ok"):
                continue
        api.send(m.telegram_id, text, kb)
    return fallback


def announce_operation(
    op: Operation, *, author: TelegramMember | None = None, from_site: bool = False
):
    """After a save: post to the channel, tell the wallet owner if someone else booked
    it, and re-check the bonus when a client paid (saveTx_)."""
    try:
        bal = S.balance(op.member)
        card = op_card(op, bal)
        to_channel(("🌐 <i>Saytdan</i>\n" if from_site else "") + card, op.receipt_file_id or None)
        if author is None or author.pk != op.member_id:
            head = (
                "💸 Sizga pul berildi:\n\n"
                if op.kind == OpKind.INCOME
                else "ℹ️ Hamyoningizga yozildi:\n\n"
            )
            api.send(op.member.telegram_id, head + card, KB_STAFF)
        if (
            op.kind == OpKind.INCOME
            and op.order_ref
            and op.category.code in (CAT_ADVANCE, CAT_REST)
        ):
            from .bonus import bonus_check

            bonus_check(op.order_ref, ok_hour=False)
    except Exception:  # noqa: BLE001
        log.exception("announce_operation failed for #%s", op.number)


def announce_deleted(ops: list[Operation], by_name: str):
    try:
        for t in ops[:1]:
            to_channel(f"🗑 <b>O'chirildi</b> ({esc(by_name)})\n\n" + op_card(t))
    except Exception:  # noqa: BLE001
        log.exception("announce_deleted failed")


def announce_edited(op: Operation, before: dict, by_name: str):
    """A site edit is visible like a deletion: channel post + the wallet owner (and
    the other side of a transfer) are told what changed."""
    try:
        old = f"{before.get('kind_label', '')} {money(before.get('amount'))} · {before.get('category_detail', {}).get('name', '')}"
        text = f"✏️ <b>Saytda o'zgartirildi</b> ({esc(by_name)})\nAvval: {esc(old)}\n\n" + op_card(
            op, S.balance(op.member)
        )
        to_channel(text)
        api.send(op.member.telegram_id, text)
        pair = S._pair_of(op)
        if pair:
            api.send(
                pair.member.telegram_id,
                f"✏️ <b>O'tkazma saytda o'zgartirildi</b> ({esc(by_name)})\n\n"
                + op_card(pair, S.balance(pair.member)),
            )
    except Exception:  # noqa: BLE001
        log.exception("announce_edited failed")


def announce_transfer(out: Operation, inc: Operation, by: TelegramMember | None):
    try:
        from .texts import kb_for

        api.send(
            inc.member.telegram_id,
            f"🔄 <b>{esc(out.member.name)}</b> sizga pul berdi:\n\n"
            + op_card(inc, S.balance(inc.member)),
            kb_for(inc.member),
        )
        to_admins(
            "⚠️ <b>Xodimlar o'rtasida pul berildi</b>\n👤 "
            + f"{esc(out.member.name)} → <b>{esc(inc.member.name)}</b>\n💵 <b>{money(out.amount)}</b>"
            + (f"\n📝 {esc(out.comment)}" if out.comment else "")
            + f"\n🧾 #{out.number} / #{inc.number}",
            exclude=by,
        )
        to_channel(
            f"🔄 O'tkazma: {esc(out.member.name)} → {esc(inc.member.name)} · {money(out.amount)}"
            + (f" · {esc(out.comment)}" if out.comment else "")
        )
    except Exception:  # noqa: BLE001
        log.exception("announce_transfer failed")
