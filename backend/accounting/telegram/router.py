"""Finance bot: one Telegram update in, replies out (port of route_/onText_/onCallback_
of code.txt). Called by api/views/finance.py for updates the bot/ service forwards.

handle_update() returns False when the update is not for the finance bot (group
chats, unknown people writing anything but /start) — the bot/ service then answers
with its usual site greeting.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta

from constance import config
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models import F

from core.exceptions import ServiceError
from oauth.models import TelegramMember, TelegramRole

from .. import services as S
from ..finance.excel import month_xlsx
from ..finance.images import bars_png, donut_png
from ..finance.text import (
    add_months,
    cur_month,
    cur_name,
    days_between,
    ddmm,
    esc,
    fmt_cur,
    money,
    month_bounds,
    month_full,
    month_name,
    num,
    parse_amount,
    parse_money,
    parse_quick,
    signed,
    today,
    usd,
)
from ..finance_constants import (
    CAT_ADVANCE,
    CAT_FROM_BOSS,
    CAT_REST,
    CAT_REWORK,
    CAT_SALARY,
    CAT_TRANSFER,
    CategoryKind,
    OpKind,
)
from ..finance_models import (
    BotSession,
    ClientFeedback,
    FinanceCar,
    MoneyRequest,
    Operation,
    OrderBonus,
    ProcessedUpdate,
    SiteEntryTask,
    WarrantyLetter,
    Worker,
)
from . import api
from . import bonus as BN
from .api import CANCEL, b, grid, ik
from .notify import announce_deleted, announce_operation, announce_transfer, to_admins, to_channel
from .texts import (
    HELP_ADMIN,
    HELP_STAFF,
    KB_STAFF,
    KB_TASK,
    cat_label,
    draft_card,
    kb_for,
    op_card,
    order_line,
    pay_label,
    task_role_text,
    ver_line,
    worker_line,
)

log = logging.getLogger("finance.router")


# ====================================================================== context
class Ctx:
    def __init__(self, frm: dict, chat_id, session: BotSession):
        self.tg_id = int(frm["id"])
        self.uid = str(frm["id"])
        self.frm = frm
        self.chat = chat_id
        self.session = session
        self.member: TelegramMember | None = S.member_by_tg(self.tg_id)
        self.cb: dict | None = None
        self.cb_msg = None
        self.cb_photo = False

    @property
    def admin(self) -> bool:
        return bool(self.member and self.member.is_admin)

    @property
    def active(self) -> bool:
        return bool(self.member and self.member.is_active_member)

    @property
    def name(self) -> str:
        return self.member.name if self.member else self.uid

    # --- draft state
    def st(self) -> dict | None:
        return self.session.data

    def set_st(self, d: dict):
        self.session.data = d
        self.session.save(update_fields=["data", "updated_at"])

    def clr_st(self):
        self.session.data = None
        self.session.save(update_fields=["data", "updated_at"])


def send(ctx: Ctx, text: str, kb=None):
    return api.send(ctx.chat, text, kb)


def show(ctx: Ctx, text: str, kb=None):
    """Edit the message whose button was pressed, else send a new one (show_)."""
    if ctx.cb and not ctx.cb_photo:
        r = api.edit(ctx.chat, ctx.cb_msg, text, kb)
        if r.get("ok") or "not modified" in str(r.get("description", "")):
            return r
    return send(ctx, text, kb)


def show_photo(ctx: Ctx, png, caption: str, kb=None):
    if not png:
        return show(ctx, caption, kb)
    if ctx.cb and ctx.cb_photo:
        r = api.edit_photo(ctx.chat, ctx.cb_msg, png, caption, kb)
        if r.get("ok"):
            return r
    return api.send_photo(ctx.chat, png, caption, kb)


def D(v):
    return S.D(v)


# ====================================================================== entry point
JOIN_COMMAND = "/moliya"  # non-members ask to join the finance bot with this


def _command(text: str) -> str:
    return (text or "").strip().split(" ")[0].split("@")[0].lower()


def _private_sender(up: dict):
    cq, msg = up.get("callback_query"), up.get("message")
    frm = (cq or msg or {}).get("from")
    if not frm or frm.get("is_bot"):
        return None, None, None, None
    chat = (cq.get("message") or {}).get("chat") if cq else (msg or {}).get("chat")
    if not chat or chat.get("type") != "private":
        return None, None, None, None
    return frm, chat, cq, msg


def claims(up: dict) -> bool:
    """Is this update for davomat (HR) or the finance bot? Answered before the (slow)
    handling, so the site bot can fall back to its greeting immediately."""
    from hr.telegram import claims as hr_claims

    return hr_claims(up) or _finance_claims(up)


def _finance_claims(up: dict) -> bool:
    """Must agree with _route()."""
    frm, chat, cq, msg = _private_sender(up)
    if not frm:
        return False
    if cq:
        return True
    text = msg.get("text") or ""
    if _command(text) == "/start" and len(text.split()) > 1:
        return False  # /start <user_id>: site account linking; /start davomat: HR
    m = S.member_by_tg(frm["id"])
    if m:
        # blocked people (e.g. rebuilt by the importer) keep the site bot greeting
        return m.role != TelegramRole.BLOCKED
    return _command(text) == JOIN_COMMAND


@contextmanager
def _user_lock(telegram_id: int):
    """One update per person at a time (two quick button presses must not both save),
    without keeping a transaction open while we talk to Telegram."""
    key = int(telegram_id) % 2_147_483_647
    with connection.cursor() as c:
        c.execute("SELECT pg_advisory_lock(%s, %s)", [7301, key])
    try:
        yield
    finally:
        with connection.cursor() as c:
            c.execute("SELECT pg_advisory_unlock(%s, %s)", [7301, key])


def handle_update(up: dict, recorded: bool = False) -> bool:
    """Handle one update. No outer transaction on purpose: Bot API calls can be slow
    and must not hold row locks; each service call is atomic on its own.
    recorded=True: dispatch() already stored it in ProcessedUpdate (the outbox)."""
    uid = up.get("update_id")
    if uid is not None and not recorded:
        try:
            with transaction.atomic():
                ProcessedUpdate.objects.create(update_id=uid)
        except IntegrityError:
            return True  # Telegram retry of an update we already handled
    sender = _sender_id(up)
    if sender is None:
        return False
    with _user_lock(sender):
        # davomat (HR) first, like DV.handle in the Apps Script: group reports,
        # `dv:` buttons, davomat commands and the answers it is waiting for
        from hr.telegram import handle as hr_handle

        if hr_handle(up):
            return True
        frm, chat, cq, msg = _private_sender(up)
        if not frm:
            return False
        return _handle_finance(up, frm, chat, cq, msg)


def _sender_id(up: dict):
    """Whose update this is (the per-user lock key). Membership changes are keyed by
    the member, not the actor: a join/leave done by another bot still counts."""
    for key in ("my_chat_member", "chat_member"):
        ev = up.get(key)
        if ev:
            user = (ev.get("new_chat_member") or {}).get("user") or ev.get("from") or {}
            return user.get("id") or (ev.get("chat") or {}).get("id")
    for key in ("callback_query", "message"):
        frm = (up.get(key) or {}).get("from")
        if frm:
            return None if frm.get("is_bot") else frm["id"]
    return None


def _handle_finance(up: dict, frm, chat, cq, msg) -> bool:
    """The finance bot part (called with the per-user lock held)."""
    session, _ = BotSession.objects.get_or_create(telegram_id=int(frm["id"]))
    if session.data and session.updated_at and S.now() - session.updated_at > timedelta(hours=6):
        session.data, session.flow_messages = None, []
    ctx = Ctx(frm, chat["id"], session)
    tracker = api.Tracker(chat["id"])
    if msg:
        tracker.ids.append(msg.get("message_id"))
    api.set_tracker(tracker)
    try:
        handled = _route(ctx, cq, msg)
    except ServiceError as e:
        send(ctx, f"❗ {esc(e.message)}")
        handled = True
    finally:
        api.set_tracker(None)
    # keep the ids of this flow's messages so «❌ Bekor qilish» can delete them
    session.refresh_from_db(fields=["data"])
    if not getattr(tracker, "done", False):
        session.flow_messages = (
            (list(session.flow_messages or []) + tracker.ids)[-80:] if session.data else []
        )
        session.save(update_fields=["flow_messages"])
    return handled


_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="finance-bot")


def run_recorded(up: dict):
    """Handle an update stored by dispatch() and mark it done (also used by the
    scheduler to replay updates a restart interrupted)."""
    uid = up.get("update_id")
    ProcessedUpdate.objects.filter(update_id=uid).update(attempts=F("attempts") + 1)
    try:
        handle_update(up, recorded=True)
    finally:
        ProcessedUpdate.objects.filter(update_id=uid).update(done=True, payload=None)


def _run(up: dict):
    close_old_connections()
    try:
        run_recorded(up)
    except Exception:  # noqa: BLE001
        log.exception("finance update failed")
    finally:
        close_old_connections()


def dispatch(up: dict) -> bool:
    """Webhook entry: decide quickly, store the update (outbox), handle it in a worker
    thread so a slow Telegram call never ties up the site's request thread."""
    if not claims(up):
        return False
    uid = up.get("update_id")
    if uid is None:
        return False
    try:
        with transaction.atomic():
            ProcessedUpdate.objects.create(update_id=uid, payload=up, done=False)
    except IntegrityError:
        return True  # a Telegram retry: already queued/handled
    _executor.submit(_run, up)
    return True


def _route(ctx: Ctx, cq, msg) -> bool:
    _sync_profile(ctx)
    if cq:
        ctx.cb, ctx.cb_msg = cq, cq["message"]["message_id"]
        ctx.cb_photo = bool(cq["message"].get("photo"))
        data = cq.get("data") or ""
        api.answer_callback(cq["id"], "❌ Bekor qilindi" if data == "cancel" else "")
        on_callback(ctx, data)
        return True
    text = (msg.get("text") or "").strip()
    is_image = bool(msg.get("photo")) or (
        msg.get("document") and str(msg["document"].get("mime_type", "")).startswith("image/")
    )
    if not ctx.member:
        # Plain /start from a non-member keeps the site bot's own greeting;
        # joining the finance bot is an explicit /moliya.
        if _command(text) == JOIN_COMMAND:
            return start(ctx)
        return False
    if is_image:
        on_photo(ctx, msg)
        return True
    if text.startswith("/"):
        return on_command(ctx, text)
    if text:
        on_text(ctx, text)
        return True
    return False


def _sync_profile(ctx: Ctx):
    """Keep the Telegram username fresh; site users are linked by telegram_id."""
    m = ctx.member
    if not m:
        return
    uname = ctx.frm.get("username") or ""
    if uname != m.username:
        m.username = uname
        m.save(update_fields=["username", "updated_at"])


# ====================================================================== start / commands
def _full_name(frm) -> str:
    return (
        " ".join(x for x in [frm.get("first_name"), frm.get("last_name")] if x)
        or frm.get("username")
        or str(frm["id"])
    )


def start(ctx: Ctx) -> bool:
    if not ctx.member:
        send(
            ctx,
            "Assalomu alaykum! 👋\nBu ser-mebel.uz boti.\n\n💰 <b>Moliya</b> (kirim-chiqim, hamyon) bo'limidan foydalanish uchun ro'yxatdan o'ting — rahbar tasdiqlaydi.",
            ik([[b("✅ Ro'yxatdan o'tish", "join")]]),
        )
        return True
    m = ctx.member
    if m.role == TelegramRole.PENDING:
        send(ctx, "⏳ So'rovingiz rahbar tomonidan hali tasdiqlanmagan.")
        return True
    if not ctx.active:
        return False
    ctx.clr_st()
    if m.is_task_only:
        send(
            ctx,
            f"Assalomu alaykum, {esc(m.name)}! 👋\n\n{task_role_text(m)}\n\n«📋 Vazifalarim» — bajarilmagan ishlaringiz.",
            KB_TASK,
        )
        return True
    send(
        ctx,
        f"Assalomu alaykum, {esc(m.name)}! 👋\nPastdagi tugmalardan foydalaning.\n\n💳 Hamyon: <b>{money(S.balance(m))}</b>",
        kb_for(m),
    )
    return True


def join(ctx: Ctx):
    m, created = S.register_member(ctx.tg_id, _full_name(ctx.frm), ctx.frm.get("username") or "")
    ctx.member = m
    if not created:
        return show(
            ctx,
            (
                "⏳ So'rovingiz yuborilgan. Rahbar tasdiqlashini kuting."
                if m.role == TelegramRole.PENDING
                else "Siz allaqachon ro'yxatdasiz. /start"
            ),
        )
    show(ctx, "✅ So'rovingiz rahbarga yuborildi. Tasdiqlangach xabar keladi.")
    text = (
        f"🆕 Yangi xodim so'rovi: <b>{esc(m.name)}</b> (@{esc(m.username or '-')}, ID {m.telegram_id})"
        + (f"\n🌐 Saytdagi profil: {esc(m.user)}" if m.user_id else "")
    )
    kb = ik(
        [
            [
                b("✅ Qabul qilish", f"approve:{m.telegram_id}"),
                b("🚫 Rad etish", f"reject:{m.telegram_id}"),
            ]
        ]
    )
    if S.admins():
        to_admins(text, kb)
    else:  # nobody is an admin yet: the site's superusers decide
        from oauth.models import User

        for u in User.objects.filter(is_superuser=True, is_active=True, telegram_id__isnull=False):
            api.send(
                u.telegram_id,
                text
                + "\n\n<i>Moliya botida hali rahbar yo'q — saytda Moliya → Telegram a'zolar bo'limida rol bering.</i>",
            )


def on_command(ctx: Ctx, text: str) -> bool:
    parts = text.split()
    cmd, args = parts[0].split("@")[0].lower(), parts[1:]
    if cmd == "/start":
        if args:  # /start <user_id>: site account linking — handled by the bot service
            return False
        return start(ctx)
    if cmd == JOIN_COMMAND:
        return start(ctx)
    if cmd == "/myid":
        send(ctx, f"Sizning Telegram ID: <code>{ctx.uid}</code>")
        return True
    if not ctx.active:
        return start(ctx)
    m = ctx.member
    if cmd in ("/yordam", "/help"):
        send(
            ctx,
            (HELP_ADMIN if ctx.admin else (task_role_text(m) if m.is_task_only else HELP_STAFF))
            + ver_line(),
            kb_for(m),
        )
    elif cmd in ("/bekor", "/cancel"):
        ctx.clr_st()
        send(ctx, "Bekor qilindi.", kb_for(m))
    elif cmd == "/kafolat" and BN.is_receiver(m):
        kafolat_give(ctx, args[0], False) if args else kafolat_list(ctx)
    elif m.is_task_only and not ctx.admin:
        send(ctx, task_role_text(m), KB_TASK)
    elif cmd == "/ochir":
        n = re.sub(r"\D", "", args[0]) if args else ""
        send(ctx, "Masalan: /ochir 25") if not n else ask_delete(ctx, int(n))
    elif cmd == "/id":
        order_card(ctx, " ".join(args)) if args else show_orders(ctx)
    elif ctx.admin and cmd == "/ism":
        target = S.member_by_tg(args[0]) if args else None
        if len(args) < 2 or not target:
            send(ctx, "Masalan: /ism 123456789 Jasur (zakupshik)")
        else:
            target.name = " ".join(args[1:])[:255]
            target.save(update_fields=["name", "updated_at"])
            send(ctx, "✅ Ism o'zgartirildi.")
    elif ctx.admin and cmd == "/kurs":
        try:
            v = float("".join(args).replace(",", ".") or 0)
        except ValueError:
            v = 0
        config.FIN_USD_RATE = v
        send(
            ctx,
            (
                f"💱 Dollar kursi: 1 USD = {money(v)}"
                if v
                else f"💱 Markaziy bank kursi ishlatiladi: 1 USD = {money(S.usd_rate())}"
            ),
        )
    elif ctx.admin and cmd == "/topshiruv":
        handover_list(ctx)
    elif ctx.admin and cmd == "/saytchi":
        role_pick(ctx, "is_site_entry", "🌐 Saytga kirituvchi menejer")
    elif ctx.admin and cmd == "/fikrchi":
        role_pick(ctx, "is_feedback", "💬 Mijoz fikri menejeri")
    elif ctx.admin and cmd == "/shablon":
        ctx.set_st({"step": "tpl"})
        (
            send(
                ctx,
                "🖼 Hisob-kitob varaqasining fon rasmini yuboring (📎 → <b>Fayl</b> qilib yuborsangiz sifati yaxshi bo'ladi).\nOddiy dizaynga qaytish: <code>/shablon oddiy</code>\nBekor qilish: /bekor",
            )
            if not args
            else _tpl_reset(ctx)
        )
    elif ctx.admin and cmd == "/umidtest":
        info = S.order_info(args[0]) if args else None
        if not args:
            send(
                ctx,
                "Masalan: <code>/umidtest 389</code> — bonus oluvchiga boradigan Готов xabarini sizga yuboradi (hech narsa yozilmaydi).",
            )
        elif not info:
            send(ctx, f"❗ {esc(args[0])} buyurtmalarda topilmadi.")
        else:
            send(ctx, "⏳ Rasm tayyorlanmoqda…")
            BN.send_ready_card(_bonus_or_temp(info), ctx.chat, test=True)
    else:
        send(ctx, "Bunday buyruq yo'q. /yordam", kb_for(m))
    return True


def _tpl_reset(ctx: Ctx):
    config.FIN_REPORT_TEMPLATE = ""
    ctx.clr_st()
    send(ctx, "✅ Hisob-kitob varaqasi oddiy (bot chizgan) dizaynga qaytarildi.")


def _bonus_or_temp(info) -> OrderBonus:
    bn = OrderBonus.objects.filter(order_ref=info.ref).first()
    if bn:
        return bn
    return OrderBonus(
        order_ref=info.ref,
        client=info.client,
        description=info.furniture,
        total=info.total,
        currency=info.currency,
        ready_date=info.ready_date or today(),
        phone=info.phone,
    )


# ====================================================================== text
MENU_STAFF = {
    "➖ Chiqim": lambda c: start_tx(c, OpKind.EXPENSE, c.member),
    "➕ Kirim": lambda c: start_tx(c, OpKind.INCOME, c.member),
    "💳 Hamyonim": lambda c: info(c, c.uid, cur_month(), "x"),
    "📋 Operatsiyalar": lambda c: ops(c, "all" if c.admin else c.uid, cur_month(), 0),
    "🧾 Buyurtmalar": lambda c: show_orders(c),
    "📤 Oylik hisob": lambda c: month_start(c),
    "🙏 Rahbardan pul so'rash": lambda c: req_start(c),
    "🔄 Xodimga pul berish": lambda c: tr_start(c),
    "❓ Yordam": lambda c: send(
        c, (HELP_ADMIN if c.admin else HELP_STAFF) + ver_line(), kb_for(c.member)
    ),
}
MENU_ADMIN = {
    "📊 Ma'lumot": lambda c: info(c, "all", cur_month(), "x"),
    "💸 Pul berish": lambda c: give_start(c),
    "👛 Hamyonlar": lambda c: wallets_view(c),
    "🔍 Tekshiruv": lambda c: send(c, checks_text(S.checks())),
    "📥 Excel": lambda c: excel_menu(c),
}


def on_text(ctx: Ctx, text: str):
    if not ctx.active:
        start(ctx)
        return
    m = ctx.member
    if m.is_task_only:
        if text == "📋 Vazifalarim":
            ctx.clr_st()
            return tasks_view(ctx)
        if text == "❓ Yordam":
            return send(ctx, task_role_text(m) + ver_line(), KB_TASK)
        if text in MENU_STAFF:
            ctx.clr_st()
            return send(
                ctx,
                "ℹ️ Siz kirim-chiqim kiritmaysiz. Sizning vazifangiz:\n\n" + task_role_text(m),
                KB_TASK,
            )
    if text in MENU_STAFF:
        ctx.clr_st()
        return MENU_STAFF[text](ctx)
    if ctx.admin and text in MENU_ADMIN:
        ctx.clr_st()
        return MENU_ADMIN[text](ctx)

    d = ctx.st()
    if d:
        step = d.get("step")
        if step == "amount":
            val, cur = parse_money(text)
            if not val:
                return send(ctx, "❗ Summani tushunmadim. Masalan: 250000, 1.5 mln yoki 100$")
            if cur == "USD":
                d.update(cur="USD", orig=str(val), amount=None)
            else:
                d.update(cur="UZS", amount=str(round(val)))
            return next_step(ctx, d)
        if step == "rate":
            try:
                r = float(re.sub(r"\s", "", text).replace(",", "."))
            except ValueError:
                r = 0
            if r <= 0:
                return send(ctx, "❗ Kursni raqam bilan yozing, masalan: 12050")
            d["rate"] = str(r)
            d["amount"] = str(round(D(d["orig"]) * D(r)))
            return next_step(ctx, d)
        if step == "comment":
            d["com"], d["ca"] = text[:300], True
            return next_step(ctx, d)
        if step in ("req_amount", "req_reason", "req_custom"):
            return req_text(ctx, d, text)
        if step == "bpay":
            return bonus_pay_text(ctx, d, text)
        if step == "fikr":
            return send(
                ctx,
                "📸 Iltimos, mijoz fikrining <b>skrinshotini</b> (rasm) yuboring. Fikr matnini rasm izohiga yozing.\nBekor qilish: /bekor",
            )
        if step == "ord_text":
            ref = text.lstrip("#").strip()[:20]
            if not re.fullmatch(r"[\w\-А-Яа-яЁё]+", ref):
                return send(ctx, "❗ Faqat ID raqamini yozing, masalan: 406")
            info_ = S.order_info(ref)
            d["ord"], d["oa"] = (info_.ref if info_ else ref), True
            send(
                ctx,
                "✔️ "
                + (
                    order_line(info_.ref)
                    if info_
                    else f"🧾 {esc(ref)} <i>(ro'yxatda yo'q — shu ID bilan yoziladi)</i>"
                ),
            )
            return next_step(ctx, d)
        if step.startswith("tr_"):
            return tr_text(ctx, d, text)
        if step in ("receipt", "attach"):
            return send(ctx, "📎 Rasm yuboring yoki «O'tkazib yuborish»ni bosing.")
        if step.startswith("o_") or step == "month_note":
            return order_text(ctx, d, text)
        return send(ctx, "Yuqoridagi tugmalardan birini tanlang yoki /bekor.")
    q = parse_quick(text, S.all_order_ids(), S.categories())
    if q:
        return start_tx(ctx, q["kind"], ctx.member, q)
    send(
        ctx,
        "Tushunmadim 🙂 Tugmalardan foydalaning yoki «350000 furnitura 406» ko'rinishida yozing. /yordam",
        kb_for(ctx.member),
    )


def on_photo(ctx: Ctx, msg: dict):
    if not ctx.active:
        return
    fid = msg["photo"][-1]["file_id"] if msg.get("photo") else msg["document"]["file_id"]
    d = ctx.st()
    caption = str(msg.get("caption") or "")
    if ctx.admin and ((d and d.get("step") == "tpl") or caption.startswith("/shablon")):
        ctx.clr_st()
        return tpl_from_telegram(ctx, fid)
    if d and d.get("step") == "fikr":
        return fikr_photo(ctx, d, fid, caption[:300])
    if d and (d.get("step") == "receipt" or (d.get("step") == "confirm" and d.get("t") == "tx")):
        d["rcpt"], d["ra"] = fid, True
        return next_step(ctx, d)
    if d and d.get("step") == "attach":
        ctx.clr_st()
        op = Operation.objects.filter(number=d["tx"]).first()
        if op:
            op.receipt_file_id = fid
            op.save(update_fields=["receipt_file_id", "updated_at"])
            send(ctx, f"📎 Chek #{op.number} ga biriktirildi.")
            to_channel("📎 Chek qo'shildi\n\n" + op_card(op), fid)
        return
    if ctx.member.is_task_only:
        return send(ctx, task_role_text(ctx.member), KB_TASK)
    q = parse_quick(caption, S.all_order_ids(), S.categories())
    if q:
        q["rcpt"] = fid
        return start_tx(ctx, q["kind"], ctx.member, q)
    send(
        ctx,
        "Rasm qaysi amalga tegishli? Avval «➖ Chiqim» bosing yoki rasm ostiga <code>350000 furnitura 406</code> deb yozing.",
    )


# ====================================================================== kirim / chiqim flow
def start_tx(ctx: Ctx, kind: str, target: TelegramMember, q: dict | None = None):
    if ctx.member.is_task_only:
        return send(ctx, task_role_text(ctx.member), KB_TASK)
    d = {
        "t": "tx",
        "kind": kind,
        "uid": target.telegram_id,
        "author": ctx.tg_id,
        "amount": None,
        "cur": "UZS",
        "orig": None,
        "rate": None,
        "cat": None,
        "ord": None,
        "com": None,
        "rcpt": None,
        "oa": False,
        "ca": False,
        "ra": False,
    }
    if q:
        cat = S.category(q["cat"]) if q.get("cat") else None
        if q.get("cat") == CAT_SALARY and kind == OpKind.EXPENSE:
            w = _find_worker(q["com"])
            if w:
                d["worker"] = w
        if q["cur"] == "USD":
            d.update(cur="USD", orig=str(q["val"]))
        else:
            d["amount"] = str(round(q["val"]))
        if cat and not (cat.admin_only and not ctx.admin):
            d["cat"] = cat.code
        if q.get("ord") and not (cat and cat.no_order) and q.get("cat") != CAT_SALARY:
            d["ord"], d["oa"] = q["ord"], True
        if q.get("com"):
            d["com"], d["ca"] = q["com"], True
        if q.get("rcpt"):
            d["rcpt"], d["ra"] = q["rcpt"], True
    return next_step(ctx, d)


def _find_worker(text: str) -> str | None:
    t = f" {str(text or '').lower()} "
    for w in Worker.objects.filter(is_active=True):
        n = w.name.lower().split(" ")[0]
        if len(n) > 2 and n in t:
            return w.name
    return None


def cat_kb(admin: bool):
    cats = [c for c in S.categories(CategoryKind.EXPENSE) if admin or not c.admin_only]
    return ik(grid([b(f"{c.emoji} {c.name}", f"cat:{c.code}") for c in cats], 2) + [[CANCEL]])


def src_kb():
    # «Rahbardan» is not here: only the boss books it, through «💸 Pul berish».
    cats = [c for c in S.categories(CategoryKind.INCOME) if c.code != CAT_FROM_BOSS]
    return ik([[b(f"{c.emoji} {c.name}", f"cat:{c.code}")] for c in cats] + [[CANCEL]])


def order_kb(kind: str, cat_code: str):
    general = True
    if kind != OpKind.INCOME:
        want = ["jarayonda", "yangi"] if cat_code == "material" else ["jarayonda"]
    elif cat_code == CAT_ADVANCE:
        want, general = ["yangi", "jarayonda", "kutish"], False
    elif cat_code == CAT_REST:
        want, general = ["kutish", "yakun"], False
    else:
        want = ["yangi", "jarayonda", "kutish", "yakun"]
    ic = {"yangi": "🆕 ", "yakun": "✅ ", "jarayonda": "🧾 ", "kutish": "⏳ "}
    lst = S.open_orders(want)
    rows = [
        [b(f"{ic.get(o.bucket, '')}{o.ref} · {o.client[:28]}", f"ord:{o.ref}")] for o in lst[:60]
    ]
    if general or not lst:
        rows.append([b("🏭 Umumiy (buyurtmasiz)", "ord:-")])
    cat = S.category(cat_code)
    if kind == OpKind.EXPENSE and cat and cat.archive:
        rows.append([b("🗄 Arxiv ID (Готов, oxirgi 4 oy)", "oarx:0")])
    rows.append([CANCEL])
    return ik(rows)


def arx_kb(page: int):
    lst = S.archive_orders()
    n = 30
    pages = max(1, -(-len(lst) // n))
    pg = max(0, min(page, pages - 1))
    rows = [
        [b(f"🗄 {x.ref} · {x.client[:24]} ({ddmm(x.ready_date)[:5]})", f"ord:{x.ref}")]
        for x in lst[pg * n : pg * n + n]
    ]
    nav = []
    if pg > 0:
        nav.append(b("◀️", f"oarx:{pg - 1}"))
    if (pg + 1) * n < len(lst):
        nav.append(b("▶️", f"oarx:{pg + 1}"))
    rows += [nav, [b("⬅️ Orqaga (faol buyurtmalar)", "oarx:back")], [CANCEL]]
    return ik(rows), len(lst), pg, pages


def skip_kb(tag: str):
    return ik([[b("⏭ O'tkazib yuborish", f"skip:{tag}")], [CANCEL]])


def group_kb():
    groups = _worker_groups()
    return ik([[b(_group_label(g), f"wg:{i}")] for i, g in enumerate(groups)] + [[CANCEL]])


def _worker_groups() -> list[str]:
    out = []
    for w in Worker.objects.filter(is_active=True):
        if w.group not in out:
            out.append(w.group)
    return out


def _is_team(g: str) -> bool:
    return bool(re.search(r"komanda|команда|brigada|бригада", g, re.I))


def _group_label(g: str) -> str:
    gl = g.lower()
    icon = (
        "🔧"
        if _is_team(g)
        else (
            "🏭"
            if re.search(r"zavod|завод|sex|цех", gl)
            else (
                "🎨"
                if re.search(r"molyar|маляр|bo'yoq", gl)
                else "🗂" if re.search(r"ofis|офис", gl) else "👥"
            )
        )
    )
    boss = None
    if _is_team(g):
        boss = Worker.objects.filter(
            group=g, is_active=True, position__iregex=r"bosh|бош|глав|brigadir"
        ).first()
    return f"{icon} {_short_group(g)}" + (f" · {boss.name}" if boss else "")


def _short_group(g: str) -> str:
    return re.sub(r"\s*\(.*\)\s*$", "", g)


def _team_name(g: str) -> str:
    return "👥 " + _short_group(g) + " (butun komanda)"


def worker_kb(gi: int):
    groups = _worker_groups()
    if gi >= len(groups):
        return group_kb()
    g = groups[gi]
    rows = []
    for w in Worker.objects.filter(is_active=True, group=g):
        crown = "👑 " if re.search(r"bosh|бош|глав", w.position, re.I) else ""
        rows.append([b(crown + w.name + (f" — {w.position}" if w.position else ""), f"wk:{w.id}")])
    if _is_team(g):
        rows.append([b(_team_name(g), f"wt:{gi}")])
    rows.append([b("⬅️ Orqaga", "wb"), CANCEL])
    return ik(rows)


def next_step(ctx: Ctx, d: dict):
    def say(text, kb=None):
        ctx.set_st(d)
        return send(ctx, text, kb)

    kind = d["kind"]
    if not d.get("amount") and not d.get("orig"):
        d["step"] = "amount"
        return say(
            f"💵 {'Chiqim' if kind == OpKind.EXPENSE else 'Kirim'} summasini yozing:\n<i>masalan: 250000, 250 ming, 1.5 mln yoki 100$</i>",
            ik([[CANCEL]]),
        )
    if d.get("cur") == "USD" and not d.get("amount"):
        if not d.get("rate") and not d.get("mr"):
            r = S.usd_rate()
            d["rate"] = str(r) if r else None
        if not d.get("rate"):
            d["step"] = "rate"
            return say("💱 1 USD necha so'm? Kursni yozing (masalan 12050):", ik([[CANCEL]]))
        d["amount"] = str(round(D(d["orig"]) * D(d["rate"])))
    if not d.get("cat"):
        if d.get("give"):
            d["cat"] = CAT_FROM_BOSS
        else:
            d["step"] = "category"
            return say(
                "🗂 Nimaga sarflandi?" if kind == OpKind.EXPENSE else "📥 Pul qayerdan keldi?",
                cat_kb(ctx.admin) if kind == OpKind.EXPENSE else src_kb(),
            )
    cat = S.category(d["cat"])
    if kind == OpKind.EXPENSE and d["cat"] == CAT_SALARY and not d.get("worker"):
        d["step"] = "worker"
        return say("👷 Kimga oylik berildi? Bo'limni tanlang:", group_kb())
    if kind == OpKind.EXPENSE and d["cat"] == CAT_SALARY and not d.get("pay"):
        if not ctx.admin:
            d["pay"] = "Avans"
        else:
            d["step"] = "paytype"
            return say(
                "💵 Bu <b>avansmi</b> yoki <b>oylik</b>?",
                ik([[b("💵 Avans", "pay:Avans"), b("🧾 Oylik", "pay:Oylik")], [CANCEL]]),
            )
    if kind == OpKind.EXPENSE and d["cat"] == "zapravka" and not d.get("worker"):
        d["step"] = "car"
        cars = list(FinanceCar.objects.filter(is_active=True))
        return say(
            "⛽ Qaysi mashina / kim uchun?",
            ik([[b(f"🚗 {c.name}", f"car:{c.id}")] for c in cars] + [[CANCEL]]),
        )
    no_order = kind == OpKind.EXPENSE and (d["cat"] == CAT_SALARY or (cat and cat.no_order))
    if no_order:
        d["oa"], d["ord"] = True, None
    if kind == OpKind.EXPENSE and d["cat"] == CAT_REWORK and not d.get("oa"):
        d["step"] = "ord_text"
        return say(
            "🔁 Peredelka — qaysi mijoz uchun?\n🧾 Buyurtma ID raqamini yozing (masalan <b>406</b>):",
            ik([[CANCEL]]),
        )
    if not d.get("oa") and not (kind == OpKind.INCOME and d["cat"] == CAT_FROM_BOSS):
        d["step"] = "order"
        q = (
            "🧾 Qaysi bitgan buyurtma (oxirgi 30 kun)?"
            if d["cat"] == CAT_REST
            else (
                "🧾 Qaysi yangi buyurtma (mijoz ID)?"
                if d["cat"] == CAT_ADVANCE
                else "🧾 Qaysi buyurtma (mijoz ID) uchun?"
            )
        )
        return say(q, order_kb(kind, d["cat"]))
    if not d.get("ca"):
        d["step"] = "comment"
        if kind == OpKind.EXPENSE and cat and cat.no_order:
            return say("📝 Tavsif yozing — nima uchun sarflandi:", ik([[CANCEL]]))
        return say(
            f"📝 Qisqa izoh yozing ({'nima olindi, nechta' if kind == OpKind.EXPENSE else 'izoh'}):",
            skip_kb("comment"),
        )
    d["step"] = "confirm"
    rows = [
        [b("✅ Saqlash", "save")],
        [b("✏️ Summa", "edit:amount"), b("🗂 Kategoriya", "edit:category")]
        + ([] if no_order else [b("🧾 Buyurtma", "edit:order")]),
    ]
    if d.get("cur") == "USD":
        rows.append([b("💱 Kursni o'zgartirish", "edit:rate")])
    rows.append([CANCEL])
    return say(draft_card(d), ik(rows))


def save_tx(ctx: Ctx, d: dict | None):
    if not d or d.get("step") != "confirm":
        return
    ctx.clr_st()
    owner = S.member_by_tg(d["uid"])
    if not owner:
        return send(ctx, "❗ Xodim topilmadi.")
    op = S.create_operation(
        member=owner,
        author=ctx.member,
        kind=d["kind"],
        amount=D(d["amount"]),
        category_code=d["cat"],
        currency=d.get("cur") or "UZS",
        orig_amount=D(d["orig"]) if d.get("orig") else None,
        rate=D(d["rate"]) if d.get("rate") else None,
        order_ref=d.get("ord"),
        comment=d.get("com") or "",
        receipt_file_id=d.get("rcpt") or "",
        worker=d.get("worker") or "",
        pay_type=d.get("pay") or "",
        actor_admin=ctx.admin,
    )
    bal = S.balance(owner)
    btns = [b("🗑 O'chirish", f"del:{op.number}")]
    if op.kind == OpKind.EXPENSE and not op.receipt_file_id:
        btns.insert(0, b("📎 Chek qo'shish", f"rcpt:{op.number}"))
    show(ctx, "✅ Saqlandi!\n\n" + op_card(op, bal), ik([btns]))
    announce_operation(op, author=ctx.member)
    if bal < 0 and op.kind == OpKind.EXPENSE and owner.pk == ctx.member.pk:
        send(
            ctx,
            f"⚠️ Hamyoningiz manfiy: {money(bal)}. Kirim yozilmay qolgan bo'lsa yoki pul kerak bo'lsa, rahbardan so'rang.",
            ik([[b("🙏 Rahbardan pul so'rash", "go:req")]]),
        )


def ask_delete(ctx: Ctx, number: int):
    op = Operation.objects.select_related("member", "category").filter(number=number).first()
    if not S.can_delete(ctx.member, op):
        return send(
            ctx,
            "❗ Bu amalni o'chira olmaysiz (topilmadi, sizniki emas yoki 2 kundan eski — rahbarga murojaat qiling).",
        )
    send(
        ctx,
        "🗑 Rostdan o'chirilsinmi?\n\n" + op_card(op),
        ik([[b("🗑 Ha, o'chirish", f"delok:{number}"), b("Yo'q", "cancel")]]),
    )


# ====================================================================== views
def _scope_member(ctx: Ctx, scope: str) -> TelegramMember | None:
    if not ctx.admin:
        return ctx.member
    return None if scope == "all" else S.member_by_tg(scope)


def info(ctx: Ctx, scope: str, ym: str, side: str):
    if not ctx.admin:
        scope = ctx.uid
    member = _scope_member(ctx, scope)
    if scope != "all" and not member:
        return send(ctx, "Xodim topilmadi.")
    s, e = month_bounds(ym)
    sm = S.summary(s, e, member)
    items = sm["expense_by_category"] if side == "x" else sm["income_by_category"]
    tot = sum(i["sum"] for i in items) or 1
    who = "🏢 Ser mebel (hammasi)" if member is None else f"👤 {esc(member.name)}"
    lines = [
        f"📊 <b>Ma'lumot · {month_name(ym)}</b>",
        who,
        "",
        f"🔴 Xarajatlar: <b>{num(-sm['expense'])}</b>",
        f"🟢 Daromadlar: <b>{num(sm['income'])}</b>",
        f"💠 <b>Balans: {num(sm['balance'])} so'm</b>",
    ]
    if member is None:
        lines.append(
            f"💸 Xodimlarga berildi: <b>{num(sm['given_to_staff'])}</b> <i>(daromad emas)</i>"
        )
        if sm["boss_personal"]:
            lines.append(f"👔 Rahbar xarajatlari (alohida): <b>{num(sm['boss_personal'])}</b>")
        if sm["home"]:
            lines.append(f"🏠 Uy uchun (alohida): <b>{num(sm['home'])}</b>")
        if sm["transfers"]:
            lines.append(f"🔄 Xodimlar o'rtasida o'tkazildi: {num(sm['transfers'])}")
    elif not member.is_admin:
        lines.append(f"👛 Hamyonda hozir: <b>{money(S.balance(member))}</b>")
    lines += ["", "<b>Xarajatlar:</b>" if side == "x" else "<b>Daromadlar:</b>"]
    if not items:
        lines.append("— bu oyda yo'q")
    for i in items[:9]:
        lines.append(
            f"{i['emoji']} {esc(i['name'])} — <b>{num(-i['sum'] if side == 'x' else i['sum'])}</b> · {round(i['sum'] * 100 / tot)}% · {i['n']} op."
        )
    if len(items) > 9:
        lines.append(f"… yana {len(items) - 9} ta")
    if side == "x" and sm["salary_by_worker"]:
        lines += ["", "<b>👷 Oylik — kimga:</b>"]
        for n, v in sm["salary_by_worker"][:10]:
            lines.append(f"• {esc(n)} — {num(v)}")
        if len(sm["salary_by_worker"]) > 10:
            lines.append(f"… yana {len(sm['salary_by_worker']) - 10} kishi")
    top = items[0] if items else None
    png = donut_png(
        items,
        top["name"] if top else "Ma'lumot yo'q",
        (num(-top["sum"] if side == "x" else top["sum"]) + " UZS") if top else "",
    )
    prev_, next_ = add_months(ym, -1), add_months(ym, 1)
    nav = [b(f"◀️ {month_name(prev_)}", f"inf:{scope}:{prev_}:{side}")]
    if ym < cur_month():
        nav.append(b(f"{month_name(next_)} ▶️", f"inf:{scope}:{next_}:{side}"))
    kb = [
        nav,
        [
            b(("● " if side == "x" else "") + "🔴 Xarajatlar", f"inf:{scope}:{ym}:x"),
            b(("● " if side == "d" else "") + "🟢 Daromadlar", f"inf:{scope}:{ym}:d"),
        ],
        [b("📋 Operatsiyalar", f"ops:{scope}:{ym}:0"), b("📈 Oylar", f"mon:{scope}")],
    ]
    if ctx.admin:
        kb.append(
            [
                (
                    b("👤 Xodim bo'yicha", f"who:{ym}")
                    if scope == "all"
                    else b("🏢 Hammasi", f"inf:all:{ym}:{side}")
                ),
                b("📥 Excel", f"xls:{ym}"),
            ]
        )
    show_photo(ctx, png, "\n".join(lines), ik(kb))


def ops(ctx: Ctx, scope: str, ym: str, page: int):
    if not ctx.admin:
        scope = ctx.uid
    member = _scope_member(ctx, scope)
    s, e = month_bounds(ym)
    rows = list(S.period_ops(s, e, member).order_by("-date", "-number"))
    per = 18
    pages = max(1, -(-len(rows) // per))
    page = max(0, min(int(page or 0), pages - 1))
    scope_all = member is None
    day_tot = {}
    for t in rows:
        internal = t.category.excluded if scope_all else t.category.code == CAT_TRANSFER
        if not internal:
            day_tot[t.date] = day_tot.get(t.date, 0) + t.signed_amount
    who = "" if member is None else f" · {esc(member.name)}"
    lines = [f"📋 <b>Operatsiyalar · {month_name(ym)}</b>{who}"]
    cur = None
    for t in rows[page * per : (page + 1) * per]:
        if t.date != cur:
            cur = t.date
            lines += [
                "",
                f"📅 <b>{ddmm(t.date)}</b>   <b>{signed(day_tot.get(t.date, 0))} UZS</b>",
                "────────────",
            ]
        sign = "🟢 +" if t.kind == OpKind.INCOME else "🔴 −"
        extra = " · ".join(
            x
            for x in [
                f"👤 {esc(t.member.name)}" if scope_all else "",
                f"👷 {esc(t.worker)}" if t.worker else "",
                f"🧾 {esc(t.order_ref)}" if t.order_ref else "",
                usd(t.orig_amount) if t.currency == "USD" else "",
                "📎" if t.receipt_file_id else "",
                f"#{t.number}",
            ]
            if x
        )
        internal = t.category.excluded if scope_all else t.category.code == CAT_TRANSFER
        lines += [
            f"{cat_label(t.category)}{' ↔️' if internal else ''}   {sign}{num(t.amount)}",
            f"      <i>{(esc(t.comment[:60]) + ' · ') if t.comment else ''}{extra}</i>",
        ]
    if not rows:
        lines += ["", "Bu oyda amal yo'q."]
    if pages > 1:
        lines += ["", f"Sahifa {page + 1}/{pages}"]
    pg = []
    if page > 0:
        pg.append(b("⬅️ Oldingi", f"ops:{scope}:{ym}:{page - 1}"))
    if page < pages - 1:
        pg.append(b("Keyingi ➡️", f"ops:{scope}:{ym}:{page + 1}"))
    nav = [b(f"◀️ {month_name(add_months(ym, -1))}", f"ops:{scope}:{add_months(ym, -1)}:0")]
    if ym < cur_month():
        nav.append(b(f"{month_name(add_months(ym, 1))} ▶️", f"ops:{scope}:{add_months(ym, 1)}:0"))
    show(ctx, "\n".join(lines), ik([pg, nav, [b("📊 Ma'lumot", f"inf:{scope}:{ym}:x")]]))


def months_view(ctx: Ctx, scope: str):
    if not ctx.admin:
        scope = ctx.uid
    member = _scope_member(ctx, scope)
    series = S.months_series(member)
    lines = ["📈 <b>Oylar bo'yicha</b>" + ("" if member is None else f" · {esc(member.name)}"), ""]
    for x in series:
        lines.append(
            f"<b>{x['label']}</b>: 🟢 {num(x['income'])}  🔴 {num(x['expense'])}  = {signed(x['income'] - x['expense'])}"
        )
    png = bars_png(
        [x["label"] for x in series], [x["income"] for x in series], [x["expense"] for x in series]
    )
    show_photo(ctx, png, "\n".join(lines), ik([[b("📊 Ma'lumot", f"inf:{scope}:{cur_month()}:x")]]))


def wallets_view(ctx: Ctx):
    ym = cur_month()
    s, e = month_bounds(ym)
    rep_month = S.month_for_report()
    bal = S.balances()
    total = 0
    lines, kb = ["👛 <b>Hamyonlar</b>", ""], []
    reported = set(
        S.MonthReport.objects.filter(month=rep_month).values_list("member_id", flat=True)
    )
    for u in S.wallets():
        bv = bal.get(u.id, 0)
        last = S.last_day(u)
        if u.role == TelegramRole.STAFF:
            total += bv
        if u.is_admin:
            spent = sum(t.amount for t in S.period_ops(s, e, u) if t.kind == OpKind.EXPENSE)
            desc = f"kassa, oyda sarfladi: {money(spent)}"
        else:
            desc = ("🔴 " if bv < 0 else "") + money(bv)
        lines.append(
            ("💼 " if u.is_admin else "👤 ")
            + f"<b>{esc(u.name)}</b> — {desc}\n      oxirgi yozuv: {ddmm(last) if last else '—'}"
            + ("" if u.is_admin else f" · oylik hisob: {'✅' if u.id in reported else '⏳'}")
        )
        kb.append(
            [
                b(f"📊 {u.name[:18]}", f"inf:{u.telegram_id}:{ym}:x"),
                b("📋", f"ops:{u.telegram_id}:{ym}:0"),
                b("🔔", f"nudge:{u.telegram_id}"),
            ]
        )
    for p in TelegramMember.objects.filter(role=TelegramRole.PENDING):
        kb.append(
            [
                b(f"✅ {p.name[:18]} — qabul qilish", f"approve:{p.telegram_id}"),
                b("🚫", f"reject:{p.telegram_id}"),
            ]
        )
    if len(lines) == 2:
        lines.append("Hali hamyon yo'q.")
    lines += [
        "",
        f"💰 Xodimlar qo'lida jami: <b>{money(total)}</b>",
        "",
        "<i>Ismni o'zgartirish: /ism &lt;ID&gt; &lt;Ism&gt;</i>",
    ]
    send(ctx, "\n".join(lines), ik(kb))


def give_start(ctx: Ctx):
    st = S.staff()
    if not st:
        return send(ctx, f"Hali xodim yo'q. Xodimlar botga {JOIN_COMMAND} yozishi kerak.")
    send(
        ctx,
        "💸 Kimga pul berdingiz?",
        ik(grid([b(s.name[:25], f"give:{s.telegram_id}") for s in st], 2) + [[CANCEL]]),
    )


def checks_text(issues: list[dict], limit: int = 15) -> str:
    if not issues:
        return "✅ Tekshiruv: kamchilik topilmadi."
    lv = {"h": "🔴", "m": "🟠", "l": "🟡"}
    cnt = {"h": 0, "m": 0, "l": 0}
    for i in issues:
        cnt[i["level"]] += 1
    s = f"🔍 <b>Tekshiruv natijasi</b>\n🔴 Jiddiy: {cnt['h']}   🟠 O'rta: {cnt['m']}   🟡 Kichik: {cnt['l']}\n"
    for i in issues[:limit]:
        s += f"\n{lv[i['level']]} <b>{esc(i['title'])}</b>\n   {esc(i['detail'])}\n   💡 {esc(i['fix'])}\n"
    if len(issues) > limit:
        s += f"\n…yana {len(issues) - limit} ta — to'liq ro'yxat saytda: Moliya → Tekshiruv."
    return s


def excel_menu(ctx: Ctx):
    ym = cur_month()
    ms = [add_months(ym, -k) for k in range(4)]
    send(
        ctx,
        "📥 Qaysi oy uchun Excel?",
        ik(
            [
                [b(month_name(ms[0]), f"xls:{ms[0]}"), b(month_name(ms[1]), f"xls:{ms[1]}")],
                [b(month_name(ms[2]), f"xls:{ms[2]}"), b(month_name(ms[3]), f"xls:{ms[3]}")],
            ]
        ),
    )


def send_excel(ctx: Ctx, ym: str):
    send(ctx, "⏳ Excel tayyorlanmoqda…")
    try:
        content, name = month_xlsx(ym)
        api.send_document(ctx.chat, content, name, f"📥 {month_full(ym)} — SerMebel hisoboti")
    except Exception as e:  # noqa: BLE001
        log.exception("excel")
        send(ctx, f"❗ Excel tayyorlab bo'lmadi: {esc(e)}")


# ====================================================================== orders
def show_orders(ctx: Ctx):
    work = S.open_orders(["jarayonda"])
    fresh = S.open_orders(["yangi"])
    wait = S.open_orders(["kutish"])
    ready = S.open_orders(["yakun"])
    kb = [[b(f"🧾 {o.ref} · {o.client[:30]}", f"ocard:{o.ref}")] for o in work[:30]]
    kb += [[b(f"🆕 {o.ref} · {o.client[:30]} (faqat kirim)", f"ocard:{o.ref}")] for o in fresh[:20]]
    kb += [[b(f"⏳ {o.ref} · {o.client[:30]} (ожидание)", f"ocard:{o.ref}")] for o in wait[:20]]
    kb += [
        [b(f"✅ {o.ref} · {o.client[:30]} (tayyor, qoldiq)", f"ocard:{o.ref}")] for o in ready[:30]
    ]
    if ctx.admin:
        kb.append([b("➕ Yangi buyurtma (saytda yo'q)", "onew"), b("📁 Tugaganlar", "oclosed")])
    if not (work or fresh or wait or ready):
        return send(ctx, "Faol buyurtma yo'q.", ik(kb))
    text = f"🧾 <b>Faol buyurtmalar</b> ({len(work)})"
    if fresh:
        text += f"\n🆕 Yangi — faqat kirim/avans uchun ({len(fresh)})"
    if wait:
        text += f"\n⏳ Ожидание — avans/qoldiq (kirim) uchun ({len(wait)})"
    if ready:
        text += f"\n✅ Bitgan — qoldiq to'lov (kirim) uchun ({len(ready)})"
    send(ctx, text, ik(kb))


def order_card(ctx: Ctx, ref: str):
    o = S.order_info(ref)
    if not o:
        return send(ctx, "Buyurtma topilmadi.")
    st = S.order_stats(o.ref)
    full = ctx.admin
    label = {
        "jarayonda": "🟢 Jarayonda",
        "yangi": "🆕 Yangi (Деталировка) — kirim va «Заказ материал» chiqimi",
        "kutish": "⏳ Ожидание — faqat kirim (avans/qoldiq)",
    }.get(o.bucket)
    if o.bucket == "yakun":
        left = max(
            0, int(config.FIN_READY_DAYS or 30) - days_between(o.ready_date or today(), today())
        )
        label = f"✅ Bitgan ({ddmm(o.ready_date)}) — qoldiq to'lov (kirim) uchun, {left} kun qoldi"
    lines = [f"🧾 <b>{esc(o.ref)} — {esc(o.client)}</b>", label or "✅ Tugagan"]
    if o.phone:
        lines.append(f"📞 {esc(o.phone)}")
    lines.append("")
    if full:
        lines.append(
            f"💼 Shartnoma: <b>{fmt_cur(o.total, o.currency)} {cur_name(o.currency)}</b>"
            + (f" (≈ {money(o.price_uzs)})" if o.currency == "USD" else "")
        )
        if o.paid is not None:
            lines.append(
                f"💰 Saytda olingan: {fmt_cur(o.paid, o.currency)} · qoldiq {fmt_cur(o.rest or 0, o.currency)}"
            )
    lines.append(f"🔴 Sarflandi: <b>{money(st['spent'])}</b>")
    if st["collected"] or full:
        lines.append(
            f"💰 Botda yozilgan mijoz to'lovlari (avans + qoldiq): {money(st['collected'])}"
        )
    if full and o.price_uzs:
        pct = round(st["spent"] * 100 / o.price_uzs)
        p = min(10, max(0, pct // 10))
        lines.append("▓" * p + "░" * (10 - p) + f" {pct}% sarflandi")
        profit = o.price_uzs - st["spent"]
        lines.append(("📈 Foyda: <b>" if profit >= 0 else "📉 Zarar: <b>") + money(profit) + "</b>")
    if st["cats"]:
        lines += ["", "<b>Xarajatlar:</b>"]
        for c, v in sorted(st["cats"].items(), key=lambda kv: -kv[1]):
            lines.append(f"{cat_label(c)} — {num(v)}")
    last = st["rows"][-6:][::-1]
    if last:
        lines += ["", "<b>Oxirgi amallar:</b>"]
        for t in last:
            lines.append(
                f"#{t.number} {t.date:%d.%m} {esc(t.member.name)}: {'+' if t.kind == OpKind.INCOME else '−'}{num(t.amount)} {esc(t.comment[:30])}"
            )
    kb = []
    if full:
        kb.append([b("🖼 Hisob-kitob varaqasi", f"oimg:{o.ref}")])
        if o.manual:
            kb.append(
                [
                    b("✏️ Narx", f"oprice:{o.ref}"),
                    b("🔄 Qayta ochish" if o.manual.is_closed else "✅ Yopish", f"otoggle:{o.ref}"),
                ]
            )
    send(ctx, "\n".join(lines), ik(kb))


def order_text(ctx: Ctx, d: dict, text: str):
    step = d["step"]
    if step == "o_id":
        ref = text.strip()[:20]
        if S.order_info(ref):
            return send(ctx, "❗ Bu ID band. Boshqasini yozing.")
        d.update(oid=ref, step="o_client")
        ctx.set_st(d)
        return send(
            ctx,
            "👤 Mijoz ismi va buyurtma nomi:\n<i>masalan: Назира — oshxona mebeli</i>",
            ik([[CANCEL]]),
        )
    if step == "o_client":
        d.update(client=text[:80], step="o_phone")
        ctx.set_st(d)
        return send(ctx, "📞 Mijoz telefoni:", skip_kb("phone"))
    if step == "o_phone":
        d.update(phone=text[:30], step="o_price")
        ctx.set_st(d)
        return send(ctx, "💼 Shartnoma summasi (so'm yoki $):", skip_kb("price"))
    if step in ("o_price", "o_newprice"):
        val, cur = parse_money(text)
        if not val:
            return send(ctx, "❗ Summani tushunmadim.")
        p = val
        if cur == "USD":
            r = S.usd_rate()
            if not r:
                return send(ctx, "❗ Dollar kursi yo'q — so'mda yozing yoki /kurs 12050")
            p = round(val * r)
        if step == "o_price":
            d["price"] = str(round(p))
            return finish_order(ctx, d)
        o = S.order_info(d["oid"])
        if o and o.manual:
            o.manual.price = S.q2(round(p))
            o.manual.save(update_fields=["price"])
        ctx.clr_st()
        send(ctx, f"✅ Narx yangilandi: {money(p)}")
        return order_card(ctx, d["oid"])
    if step == "month_note":
        d["note"] = text[:300]
        return month_submit(ctx, d)


def finish_order(ctx: Ctx, d: dict):
    mo = S.create_manual_order(
        d["oid"], d.get("client", ""), d.get("phone", ""), D(d.get("price") or 0)
    )
    ctx.clr_st()
    send(
        ctx,
        f"✅ Buyurtma ochildi: <b>{esc(mo.ref)}</b> · {esc(mo.client)}\nEndi xodimlar xarajat yozganda shu ID ni tanlaydi.",
    )
    to_channel(
        f"🆕 Yangi buyurtma <b>{esc(mo.ref)}</b>\n👤 {esc(mo.client)}"
        + (f"\n💼 {money(mo.price)}" if mo.price else "")
    )


# ====================================================================== transfers between staff
def tr_start(ctx: Ctx):
    lst = [u for u in S.wallets() if u.pk != ctx.member.pk]
    if not lst:
        return send(ctx, "Boshqa xodim yo'q.")
    send(
        ctx,
        f"🔄 Kimga pul berdingiz?\n💳 Hamyoningizda: <b>{money(S.balance(ctx.member))}</b>",
        ik(
            grid(
                [
                    b(("👔 " if u.is_admin else "👤 ") + u.name[:22], f"trto:{u.telegram_id}")
                    for u in lst
                ],
                2,
            )
            + [[CANCEL]]
        ),
    )


def tr_text(ctx: Ctx, d: dict, text: str):
    if d["step"] == "tr_amount":
        v = parse_amount(text)
        if not v:
            return send(ctx, "❗ Summani tushunmadim. Masalan: 300000 yoki 1.5 mln")
        d.update(amount=str(round(v)), step="tr_com")
        ctx.set_st(d)
        return send(
            ctx,
            "📝 Nima uchun berdingiz? (masalan: «zapravkaga», «406 ga material»):",
            ik([[b("⏭ O'tkazib yuborish", "skip:trcom")], [CANCEL]]),
        )
    if d["step"] == "tr_com":
        d["com"] = text[:300]
        return tr_confirm(ctx, d)
    send(ctx, "«✅ Tasdiqlash» tugmasini bosing yoki /bekor.")


def tr_confirm(ctx: Ctx, d: dict):
    d["step"] = "tr_confirm"
    ctx.set_st(d)
    bal = S.balance(ctx.member)
    left = bal - D(d["amount"])
    send(
        ctx,
        f"<b>🔄 Pul berish — tekshiring:</b>\n\n👤 {esc(ctx.member.name)} → <b>{esc(d['toName'])}</b>\n💵 <b>{money(d['amount'])}</b>"
        + (f"\n📝 {esc(d['com'])}" if d.get("com") else "")
        + f"\n💳 Sizda qoladi: {money(left)}{' ⚠️' if left < 0 else ''}"
        + "\n\n<i>Rahbarga xabar boradi.</i>",
        ik([[b("✅ Tasdiqlash", "trok")], [CANCEL]]),
    )


def tr_save(ctx: Ctx, d: dict):
    ctx.clr_st()
    to = S.member_by_tg(d["to"])
    if not to:
        return send(ctx, "❗ Xodim topilmadi.")
    out, inc = S.create_transfer(
        sender=ctx.member,
        receiver=to,
        amount=D(d["amount"]),
        comment=d.get("com") or "",
        author=ctx.member,
    )
    show(ctx, "✅ Yozildi!\n\n" + op_card(out, S.balance(ctx.member)))
    announce_transfer(out, inc, ctx.member)


# ====================================================================== money requests
def req_start(ctx: Ctx):
    ctx.set_st({"step": "req_amount"})
    send(
        ctx,
        f"🙏 <b>Rahbardan pul so'rash</b>\n💳 Hamyoningizda hozir: <b>{money(S.balance(ctx.member))}</b>\n\n💵 Qancha kerak? Summani yozing:\n<i>masalan: 500000, 1.5 mln yoki 300$</i>",
        ik([[CANCEL]]),
    )


def _m_to_json(m: dict) -> dict:
    return {
        "amount": str(m["amount"]),
        "cur": m["cur"],
        "orig": str(m["orig"]) if m.get("orig") else None,
        "rate": str(m["rate"]) if m.get("rate") else None,
    }


def _m_from_json(j: dict) -> dict:
    return {
        "amount": D(j["amount"]),
        "cur": j["cur"],
        "orig": D(j["orig"]) if j.get("orig") else None,
        "rate": D(j["rate"]) if j.get("rate") else None,
    }


def req_text(ctx: Ctx, d: dict, text: str):
    if d["step"] == "req_amount":
        m = S.money_in(text)
        d.update(m=_m_to_json(m), step="req_reason")
        ctx.set_st(d)
        return send(
            ctx,
            "📝 Nima uchun kerak? Qisqa yozing (masalan: «406 zakazga LDSP», «ustalarga avans»):",
            ik([[b("⏭ O'tkazib yuborish", "skip:reason")], [CANCEL]]),
        )
    if d["step"] == "req_reason":
        d["reason"] = text[:300]
        return req_send(ctx, d)
    if d["step"] == "req_custom":
        m = S.money_in(text)
        ctx.clr_st()
        return req_give(ctx, d["req"], m)


def req_admin_text(req: MoneyRequest) -> str:
    m = {"amount": req.amount, "cur": req.currency, "orig": req.orig_amount}
    return (
        f"🙏 <b>Pul so'rovi #{req.number}</b>\n👤 {esc(req.member.name)}\n💵 <b>{S.money_text(m)}</b>"
        + (f"\n📝 {esc(req.reason)}" if req.reason else "")
        + f"\n💳 Hamyonida hozir: {money(S.balance(req.member))}\n🕒 {req.created_at:%d.%m %H:%M}"
    )


def req_send(ctx: Ctx, d: dict):
    ctx.clr_st()
    m = _m_from_json(d["m"])
    req = S.create_request(ctx.member, m, d.get("reason") or "")
    text = req_admin_text(req)
    label = f"{num(req.orig_amount)}$" if req.currency == "USD" else num(req.amount)
    kb = ik(
        [
            [b(f"✅ {label} berdim", f"rq_ok:{req.number}")],
            [
                b("✏️ Boshqa summa berdim", f"rq_amt:{req.number}"),
                b("❌ Rad etish", f"rq_no:{req.number}"),
            ],
        ]
    )
    msgs = []
    for a in S.admins():
        r = api.send(a.telegram_id, text, kb)
        if r.get("ok"):
            msgs.append([a.telegram_id, r["result"]["message_id"]])
    req.admin_messages = msgs
    req.save(update_fields=["admin_messages"])
    send(
        ctx,
        f"✅ So'rovingiz rahbarga yuborildi (#{req.number}).\n💵 {S.money_text(m)}"
        + (f"\n📝 {esc(req.reason)}" if req.reason else "")
        + "\n\nRahbar pul berganda hamyoningizga o'zi yoziladi va sizga xabar keladi.",
        kb_for(ctx.member),
    )


def req_close_messages(req: MoneyRequest, line: str):
    for chat, mid in req.admin_messages or []:
        api.edit(chat, mid, req_admin_text(req) + "\n\n" + line)


def req_answer(ctx: Ctx, cmd: str, number: int):
    req = MoneyRequest.objects.select_related("member").filter(number=number).first()
    if not req:
        return send(ctx, "❗ So'rov topilmadi.")
    if req.status != "pending":
        return send(ctx, f"ℹ️ Bu so'rovga allaqachon javob berilgan: {req.answer}")
    if cmd == "rq_ok":
        m = (
            S.money_in(f"{req.orig_amount}$")
            if req.currency == "USD"
            else {"amount": req.amount, "cur": "UZS", "orig": None, "rate": None}
        )
        return req_give(ctx, number, m)
    if cmd == "rq_amt":
        ctx.set_st({"step": "req_custom", "req": number})
        return send(
            ctx,
            f"✏️ {esc(req.member.name)} ga qancha berdingiz? Summani yozing (so'mda yoki $ da, masalan 250$):",
            ik([[CANCEL]]),
        )
    if cmd == "rq_no":
        S.reject_request(req, ctx.member)
        req.refresh_from_db()
        req_close_messages(req, f"❌ <b>Rad etildi</b> ({esc(ctx.member.name)})")
        api.send(
            req.member.telegram_id,
            f"❌ Pul so'rovingiz #{number} ({S.money_text({'amount': req.amount, 'cur': req.currency, 'orig': req.orig_amount})}) rad etildi. Savol bo'lsa, rahbarga murojaat qiling.",
            KB_STAFF,
        )


def req_give(ctx: Ctx, number: int, m: dict):
    req = MoneyRequest.objects.select_related("member").filter(number=number).first()
    if not req or req.status != "pending":
        return send(ctx, "ℹ️ Bu so'rovga allaqachon javob berilgan.")
    op = S.give_request(req, ctx.member, m)
    req.refresh_from_db()
    shown = S.money_text(m)
    req_close_messages(req, f"✅ <b>Berildi: {shown}</b> ({esc(ctx.member.name)})")
    bal = S.balance(req.member)
    api.send(
        req.member.telegram_id,
        f"💸 So'rovingiz #{number} bo'yicha pul berildi:\n\n" + op_card(op, bal),
        KB_STAFF,
    )
    to_channel(op_card(op, bal))
    send(ctx, f"✅ Yozildi: {esc(req.member.name)} ga {shown}. Hamyonida: {money(bal)}")


# ====================================================================== month report
def month_start(ctx: Ctx):
    ym = S.month_for_report()
    if ym != cur_month() and S.MonthReport.objects.filter(member=ctx.member, month=ym).exists():
        ym = cur_month()
    sm = S.month_summary(ctx.member, ym)
    sub = S.MonthReport.objects.filter(member=ctx.member, month=ym).exists()
    text = (
        f"📤 <b>{month_full(ym)} — oylik hisob</b>\n\nOy boshida: {money(sm['opening'])}\n🟢 Kirim: {money(sm['income'])}"
        f"\n🔴 Chiqim: {money(sm['expense'])}\n👛 Oy oxiriga qoldiq: <b>{money(sm['closing'])}</b>\nAmallar soni: {sm['count']}\n"
    )
    if sub:
        text += "\n\n✅ Bu oy hisobi topshirilgan. Qayta topshirish mumkin."
    ctx.set_st({"step": "month_confirm", "month": ym, "summary": text})
    send(
        ctx,
        text + "\n\nHamma kirim-chiqim kiritilgan bo'lsa, tasdiqlang:",
        ik(
            [
                [b("✅ Tasdiqlayman, topshirish", "msub")],
                [b("📝 Izoh bilan topshirish", "mnote")],
                [CANCEL],
            ]
        ),
    )


def month_submit(ctx: Ctx, d: dict):
    rep = S.submit_month(ctx.member, d["month"], d.get("note") or "")
    ctx.clr_st()
    send(ctx, "✅ Oylik hisob topshirildi. Rahmat!", kb_for(ctx.member))
    to_admins(
        f"📤 <b>{esc(ctx.member.name)}</b> oylik hisobni topshirdi.\n\n{d['summary']}"
        + (f"\n📝 Izoh: {esc(rep.note)}" if rep.note else "")
    )
    to_channel(
        f"📤 {esc(ctx.member.name)} — {month_full(d['month'])} hisobi topshirildi. Qoldiq: {money(rep.balance)}"
    )


# ====================================================================== bonus / «Pul oldim»
def bonus_paid_btn(ctx: Ctx, cmd: str, ref: str):
    if not BN.is_receiver(ctx.member):
        return send(ctx, "ℹ️ Bu tugma faqat bonus oluvchi va rahbar uchun.")
    bn = OrderBonus.objects.filter(order_ref=ref, status="waiting").first()
    if not bn:
        return send(
            ctx, f"ℹ️ {esc(ref)} zakazi bo'yicha bonus allaqachon yopilgan (yoki 30 kundan o'tgan)."
        )
    ms = S.money_state(bn)
    c = bn.currency
    if cmd == "bpaid":
        return send(
            ctx,
            f"💰 <b>{esc(ref)} · {esc(bn.client)}</b>\n🧮 Qoldiq: <b>{fmt_cur(ms['rest'], c)} {cur_name(c)}</b> ({'saytdan' if ms['src'] == 'sayt' else 'botdan'})\n\nMijozdan qancha oldingiz?",
            ik(
                [
                    [b(f"✅ To'liq oldim — {fmt_cur(ms['rest'], c)} {cur_name(c)}", f"bpf:{ref}")],
                    [b("➗ Qisman oldim (summa yozaman)", f"bpq:{ref}")],
                    [CANCEL],
                ]
            ),
        )
    if cmd == "bpq":
        ctx.set_st({"step": "bpay", "id": ref})
        return send(
            ctx,
            f"➗ <b>{esc(ref)}</b> — qancha oldingiz? Summani yozing (so'mda yoki $ da, masalan <code>{'500$' if c == 'USD' else '5000000'}</code>):",
            ik([[CANCEL]]),
        )
    if cmd == "bpf":
        api.clear_kb(ctx.chat, ctx.cb_msg)
        if ms["rest"] <= S.bonus_tolerance(c):
            bn = S.bonus_finish(bn, f"Yopdi: {ctx.member.name}")
            return BN.announce_bonus_done(bn)
        return bonus_pay_text(
            ctx,
            {"id": ref, "full": True},
            f"{ms['rest']}$" if c == "USD" else str(round(ms["rest"])),
        )
    if cmd == "bpok":
        if ms["rest"] > S.bonus_tolerance(c):
            return send(
                ctx,
                f"❗ Qoldiq hali <b>{fmt_cur(ms['rest'], c)} {cur_name(c)}</b> — zakazni faqat qoldiq 0 bo'lganda yopish mumkin. Olgan pulingizni «💰 Pul oldim» orqali kiriting.",
                BN.paid_kb(ref),
            )
        api.clear_kb(ctx.chat, ctx.cb_msg)
        bn = S.bonus_finish(
            bn, f"Yopdi: {ctx.member.name}" + (f" · olingan: {bn.got_text}" if bn.got_text else "")
        )
        BN.announce_bonus_done(bn)


def bonus_pay_text(ctx: Ctx, d: dict, text: str):
    bn = OrderBonus.objects.filter(order_ref=d["id"], status="waiting").first()
    if not bn:
        ctx.clr_st()
        return send(ctx, "ℹ️ Bu zakaz bo'yicha bonus allaqachon yopilgan.")
    m = S.money_in(text)
    ctx.clr_st()
    res = S.bonus_collect(bn, ctx.member, m, bool(d.get("full")))
    bn = res["bonus"]
    c = bn.currency
    rest_txt = "0" if res["full"] else f"{fmt_cur(res['rest'], c)} {cur_name(c)}"
    task = S.site_entry_create(bn.order_ref, bn.client, S.money_text(m), ctx.member.name, rest_txt)
    BN.site_entry_notify(task, ctx.member.name)
    if not ctx.admin:
        handover_ask(
            res["operation"], ctx.member.name, bn.order_ref, bn.client, S.money_text(m), rest_txt
        )
    if res["full"]:
        send(
            ctx,
            f"✅ Yozildi: {S.money_text(m)}\n🧾 {esc(bn.order_ref)} · {esc(bn.client)}\n🧮 Qoldiq: <b>0</b> — zakaz yopildi.",
        )
        return BN.announce_bonus_done(bn)
    send(
        ctx,
        f"✅ Yozildi: {S.money_text(m)}\n🧾 {esc(bn.order_ref)} · {esc(bn.client)}\n🧮 Qolgan qoldiq: <b>{rest_txt}</b>\n\nQolganini olganingizda yana «💰 Pul oldim» ni bosing.",
        BN.paid_kb(bn.order_ref),
    )


# ====================================================================== handover (/topshiruv)
def handover_kb(number: int):
    return ik(
        [
            [b("✅ Pulni qabul qildim", f"pqk:{number}")],
            [b("🗑 Men buni alohida kiritganman", f"pqd:{number}")],
        ]
    )


def handover_ask(op: Operation, who: str, ref: str, client: str, sum_txt: str, rest_txt: str):
    to_admins(
        f"💵 <b>{esc(who)}</b> mijozdan pul oldi — pul hozir uning qo'lida\n🧾 <b>{esc(ref)} · {esc(client)}</b>\n💰 <b>{sum_txt}</b>\n🧮 Mijoz qoldig'i: {rest_txt}"
        f"\n\nPulni sizga topshirganda «✅ Pulni qabul qildim» ni bosing — {esc(who)} balansidan yechiladi va sizning kassangizga o'tadi.",
        handover_kb(op.number),
    )


def handover_list(ctx: Ctx):
    lst = S.handover_pending()
    if not lst:
        return send(
            ctx,
            "✅ Topshirilmagan pul yo'q — «Pul oldim» orqali olingan hamma pul qabul qilingan yoki belgilangan.",
        )
    total = sum(t.amount for t in lst)
    send(
        ctx,
        f"💵 <b>Rahbarga hali topshirilmagan pullar</b> ({len(lst)} ta, jami {money(total)})\nHar biri uchun tanlang:\n• ✅ qabul qildim — xodim balansidan yechiladi, kassangizga o'tadi\n• 🗑 alohida kiritganman — bu yozuv o'chiriladi (ikki marta hisoblanmasin)",
    )
    for t in lst[:20]:
        amount = (
            f"{num(t.orig_amount)} $ ({money(t.amount)})"
            if t.currency == "USD"
            else money(t.amount)
        )
        send(
            ctx,
            f"🧾 #{t.number} · {ddmm(t.date)}\n👤 {esc(t.member.name)} · zakaz <b>{esc(t.order_ref)}</b>\n💰 <b>{amount}</b>",
            handover_kb(t.number),
        )


def handover_do(ctx: Ctx, cmd: str, number: int):
    if not ctx.admin:
        return send(ctx, "ℹ️ Bu tugma faqat rahbar uchun.")
    api.clear_kb(ctx.chat, ctx.cb_msg)
    op = Operation.objects.select_related("member").filter(number=number).first()
    if not op or (op.is_deleted and op.handover != "deleted"):
        return send(ctx, f"ℹ️ #{number} yozuvi topilmadi yoki o'chirilgan.")
    if op.handover:
        return send(
            ctx,
            f"ℹ️ #{op.number} allaqachon belgilangan ({'qabul qilingan' if op.handover == 'accepted' else 'o‘chirilgan'}).",
        )
    info_ = S.order_info(op.order_ref)
    client = info_.client if info_ else ""
    sum_txt = f"{num(op.orig_amount)} $" if op.currency == "USD" else money(op.amount)
    if cmd == "pqd":
        S.handover_drop(op)
        send(
            ctx,
            f"🗑 #{op.number} o'chirildi — {esc(op.member.name)} balansidan {sum_txt} olib tashlandi. Mijoz to'lovi sizning yozuvingiz bo'yicha hisoblanadi.",
        )
        return api.send(
            op.member.telegram_id,
            f"🗑 Rahbar <b>{esc(op.order_ref)} · {esc(client)}</b> bo'yicha {sum_txt} yozuvingizni o'chirdi (o'zi alohida kiritgan).\n💳 Hamyon: {money(S.balance(op.member))}",
        )
    S.handover_accept(op, ctx.member)
    send(
        ctx,
        f"✅ Qabul qilindi: {sum_txt} — {esc(op.order_ref)} · {esc(client)}\n👤 {esc(op.member.name)} balansidan yechildi, kassangizga o'tdi.",
    )
    api.send(
        op.member.telegram_id,
        f"✅ Rahbar <b>{esc(op.order_ref)} · {esc(client)}</b> bo'yicha {sum_txt} ni qabul qildi.\n💳 Hamyoningiz: {money(S.balance(op.member))}",
    )


# ====================================================================== kafolat / sayt / fikr / roles
def kafolat_give(ctx: Ctx, ref: str, from_btn: bool):
    if not BN.is_receiver(ctx.member):
        return send(ctx, "ℹ️ Bu tugma faqat bonus oluvchi va rahbar uchun.")
    w = S.warranty_give(ref, ctx.member.name)
    if from_btn:
        api.clear_kb(ctx.chat, ctx.cb_msg, ik([[b("💰 Pul oldim", f"bpaid:{w.order_ref}")]]))
    send(
        ctx,
        f"📜 ✅ Kafolat xati berildi: <b>{esc(w.order_ref)} · {esc(w.client)}</b>\n<i>«Kafolat xatlari» bo'limiga yozildi.</i>",
    )
    if not ctx.admin:
        to_admins(
            f"📜 {esc(ctx.member.name)} <b>{esc(w.order_ref)} · {esc(w.client)}</b> mijoziga kafolat xatini berdi."
        )


def kafolat_list(ctx: Ctx):
    rows = list(WarrantyLetter.objects.filter(given=False))
    if not rows:
        return send(ctx, "📜 Hamma Готов mijozlarga kafolat xati berilgan ✅")
    send(
        ctx,
        f"📜 <b>Kafolat xati berilmaganlar</b> ({len(rows)}):\n"
        + "\n".join(f"• {esc(r.order_ref)} · {esc(r.client)}" for r in rows[:40])
        + "\n\nBerganingizda: <code>/kafolat 389</code>",
        ik(
            [
                [b(f"📜 {r.order_ref} · {r.client[:22]} — berdim", f"kfx:{r.order_ref}")]
                for r in rows[:20]
            ]
        ),
    )


def role_pick(ctx: Ctx, duty: str, title: str):
    cur = [m.name for m in TelegramMember.objects.filter(**{duty: True})]
    act = TelegramMember.objects.filter(role__in=[TelegramRole.ADMIN, TelegramRole.STAFF])[:40]
    send(
        ctx,
        f"👥 <b>{title}</b>\nHozir: <b>{esc(', '.join(cur) or 'tanlanmagan')}</b>\n\nKim bo'ladi? (xodim avval botga /moliya yozib, siz qabul qilgan bo'lishi kerak)",
        ik([[b(m.name[:32], f"rol:{duty}:{m.telegram_id}")] for m in act]),
    )


def role_set(ctx: Ctx, arg: str):
    duty, _, tg = arg.partition(":")
    m = S.member_by_tg(tg)
    if not ctx.admin or not m or duty not in ("is_site_entry", "is_feedback"):
        return
    S.set_duty_exclusive(m, duty)
    what = (
        "🌐 Saytga kirituvchi: mijozdan pul olinganda sizga xabar keladi — saytda «Полученная сумма» ni to'g'rilab, «✅ Saytga kiritdim» ni bosasiz."
        if duty == "is_site_entry"
        else "💬 Mijoz fikri: zakaz Готов bo'lganiga 3 kun bo'lganda sizga xabar keladi — mijozdan fikrini olib, «📝 Fikr oldim» ni bosib skrinshot yuborasiz."
    )
    m.refresh_from_db()
    api.send(
        m.telegram_id,
        f"👋 Sizga yangi vazifa berildi.\n\n{what}\n\n"
        + ("" if m.is_admin else "Siz kirim-chiqim kiritmaysiz, oylik hisob ham so'ralmaydi. ")
        + "«📋 Vazifalarim» — bajarilmagan ishlaringiz.",
        kb_for(m),
    )
    show(ctx, f"✅ <b>{esc(m.name)}</b> tanlandi.\n\n{what}")


def tasks_view(ctx: Ctx):
    m = ctx.member
    kb, lines = [], ["📋 <b>Bajarilmagan vazifalar</b>"]
    if m.is_admin or m.is_site_entry:
        for t in SiteEntryTask.objects.filter(is_done=False)[:15]:
            lines.append(
                f"🌐 {esc(t.order_ref)} · {esc(t.client)} — {esc(t.sum_text)} ({ddmm(t.date)})"
            )
            kb.append([b(f"✅ {t.order_ref} saytga kiritdim", f"skt:{t.code}")])
    if m.is_admin or m.is_feedback:
        for f in ClientFeedback.objects.filter(status="asked")[:15]:
            lines.append(
                f"💬 {esc(f.order_ref)} · {esc(f.client)}"
                + (f" · {esc(f.phone)}" if f.phone else "")
                + f" (so'ralgan {ddmm(f.asked_date)})"
            )
            kb.append([b(f"📝 {f.order_ref} fikr oldim", f"fko:{f.order_ref}")])
    if len(lines) == 1:
        lines += ["", "✅ Hammasi bajarilgan."]
    send(ctx, "\n".join(lines), ik(kb) if kb else KB_TASK)


def sayt_done(ctx: Ctx, code: str):
    m = ctx.member
    if not (m.is_admin or m.is_site_entry):
        return send(ctx, "ℹ️ Bu tugma saytga kirituvchi menejer uchun.")
    api.clear_kb(ctx.chat, ctx.cb_msg)
    task = SiteEntryTask.objects.filter(code=code).first()
    if not task or task.is_done:
        return send(ctx, "ℹ️ Bu allaqachon belgilangan.")
    S.site_entry_done(task, m.name)
    send(
        ctx,
        f"✅ Belgilandi: {esc(task.order_ref)} · {esc(task.client)} — {esc(task.sum_text)}. Rahmat!",
    )
    BN.site_entry_done_announce(task, m.name)


def fikr_btn(ctx: Ctx, ref: str):
    m = ctx.member
    if not (m.is_admin or m.is_feedback):
        return send(ctx, "ℹ️ Bu tugma mijoz fikri menejeri uchun.")
    if ClientFeedback.objects.filter(order_ref=ref, status="received").exists():
        return send(ctx, f"ℹ️ {esc(ref)} — fikr allaqachon olingan.")
    ctx.set_st({"step": "fikr", "id": ref})
    send(
        ctx,
        f"📸 <b>{esc(ref)}</b> — mijoz fikrining <b>skrinshotini</b> yuboring.\nRasm izohiga qisqacha fikrni ham yozishingiz mumkin.\n\nBekor qilish: /bekor",
    )


def fikr_photo(ctx: Ctx, d: dict, fid: str, caption: str):
    ctx.clr_st()
    fb = ClientFeedback.objects.filter(order_ref=d["id"]).first()
    if not fb:
        info_ = S.order_info(d["id"])
        fb = ClientFeedback.objects.create(
            order_ref=d["id"], client=(info_.client if info_ else "")[:255], status="asked"
        )
    url = ""
    got = api.download_file(fid)
    if got:
        path = default_storage.save(
            f"finance/feedback/{re.sub(r'[^0-9A-Za-z_-]', '_', fb.order_ref)}.jpg",
            ContentFile(got[0]),
        )
        url = default_storage.url(path)
    S.feedback_receive(fb, ctx.member.name, caption, fid, url)
    send(
        ctx,
        f"✅ Mijoz fikri saqlandi: {esc(fb.order_ref)} · {esc(fb.client)}. Rahmat!",
        kb_for(ctx.member),
    )
    for a in S.admins():
        api.send_photo(
            a.telegram_id,
            fid,
            f"💬 <b>Mijoz fikri olindi</b>\n🧾 <b>{esc(fb.order_ref)} · {esc(fb.client)}</b>\n👤 {esc(ctx.member.name)}"
            + (f"\n📝 {esc(caption)}" if caption else ""),
        )


def tpl_from_telegram(ctx: Ctx, fid: str):
    send(ctx, "⏳ Shablon tayyorlanmoqda…")
    got = api.download_file(fid)
    if not got:
        return send(ctx, "❗ Rasmni yuklab bo'lmadi.")
    path = default_storage.save("finance/report_background.png", ContentFile(got[0]))
    config.FIN_REPORT_TEMPLATE = path
    info_ = next(iter(S.open_orders(["yakun"])), None)
    if info_:
        BN.send_ready_card(_bonus_or_temp(info_), ctx.chat, test=True)
    send(ctx, "✅ Yangi fon ulandi. Oddiy dizaynga qaytish: <code>/shablon oddiy</code>")


# ====================================================================== callbacks
def cancel_flow(ctx: Ctx):
    ids = list(ctx.session.flow_messages or [])
    if ctx.cb_msg:
        ids.append(ctx.cb_msg)
    ctx.session.data, ctx.session.flow_messages = None, []
    ctx.session.save(update_fields=["data", "flow_messages", "updated_at"])
    tr = api.get_tracker()
    if tr:
        tr.done = True
    ok = 0
    for mid in dict.fromkeys(i for i in ids if i):
        if api.delete(ctx.chat, mid).get("ok"):
            ok += 1
    if not ok:
        show(ctx, "❌ Bekor qilindi.")


def on_callback(ctx: Ctx, data: str):
    p = data.split(":")
    cmd, arg = p[0], ":".join(p[1:])
    if cmd == "join":
        return join(ctx)
    if not ctx.active:
        return
    d = ctx.st()

    def edit(text):
        return show(ctx, text)

    if cmd == "cancel":
        return cancel_flow(ctx)
    if cmd in ("bpaid", "bpok", "bpf", "bpq"):
        return bonus_paid_btn(ctx, cmd, arg)
    if cmd == "kfx":
        return kafolat_give(ctx, arg, True)
    if cmd == "skt":
        return sayt_done(ctx, arg)
    if cmd in ("pqk", "pqd"):
        return handover_do(ctx, cmd, int(arg))
    if cmd == "fko":
        return fikr_btn(ctx, arg)
    if cmd == "rol":
        return role_set(ctx, arg)
    if cmd == "tst":
        return send(
            ctx,
            (
                "🧪 Namuna. Bu tugma «✅ To'liq oldim — qoldiq» yoki «➗ Qisman oldim» ni so'raydi."
                if arg == "pul"
                else "🧪 Namuna. Bu tugma «Kafolat xatlari» ga ✅ Berildi deb yozadi."
            ),
        )
    # --- draft
    if d and d.get("step") == "worker":
        if cmd == "wg":
            ctx.set_st(d)
            groups = _worker_groups()
            gi = int(arg)
            return show(ctx, f"👷 {esc(groups[gi] if gi < len(groups) else '')}:", worker_kb(gi))
        if cmd == "wb":
            return show(ctx, "👷 Kimga oylik berildi? Bo'limni tanlang:", group_kb())
        if cmd in ("wk", "wt"):
            if cmd == "wk":
                w = Worker.objects.filter(pk=int(arg)).first()
                name = w.name if w else ""
            else:
                groups = _worker_groups()
                name = _team_name(groups[int(arg)]) if int(arg) < len(groups) else ""
            if not name:
                return
            d["worker"] = name
            edit("✔️ " + worker_line(name))
            return next_step(ctx, d)
    if cmd == "pay" and d and d.get("step") == "paytype" and arg in ("Avans", "Oylik"):
        d["pay"] = arg
        edit("✔️ " + pay_label(arg))
        return next_step(ctx, d)
    if cmd == "car" and d and d.get("step") == "car":
        car = FinanceCar.objects.filter(pk=int(arg)).first()
        d["worker"] = car.name if car else ""
        edit(f"✔️ 🚗 {esc(d['worker'])}")
        return next_step(ctx, d)
    if cmd == "cat" and d and d.get("step") == "category":
        c = S.category(arg)
        if not c or (c.admin_only and not ctx.admin):
            return
        d["cat"] = arg
        edit("✔️ " + cat_label(c))
        return next_step(ctx, d)
    if cmd == "oarx" and d and d.get("step") == "order":
        if arg == "back":
            return show(ctx, "🧾 Qaysi buyurtma (mijoz ID) uchun?", order_kb(d["kind"], d["cat"]))
        kb, n, pg, pages = arx_kb(int(arg or 0))
        if not n:
            return show(
                ctx,
                "🗄 Arxiv hozircha bo'sh (oxirgi 4 oyda «Готов» bo'lgan buyurtma topilmadi).",
                kb,
            )
        return show(
            ctx,
            f"🗄 <b>Arxiv</b> — oxirgi 4 oyda «Готов» bo'lgan buyurtmalar ({n})"
            + (f" · {pg + 1}/{pages}" if pages > 1 else "")
            + ":",
            kb,
        )
    if cmd == "ord" and d and d.get("step") == "order":
        d["ord"], d["oa"] = (None if arg == "-" else arg), True
        edit("✔️ " + order_line(d["ord"]))
        return next_step(ctx, d)
    if cmd == "skip" and d:
        step = d.get("step")
        if arg == "comment" and step == "comment":
            d["ca"] = True
        elif arg == "receipt" and step == "receipt":
            d["ra"] = True
        elif arg == "reason" and step == "req_reason":
            edit("⏭ Sababsiz")
            return req_send(ctx, d)
        elif arg == "trcom" and step == "tr_com":
            edit("⏭ Izohsiz")
            d["com"] = ""
            return tr_confirm(ctx, d)
        elif arg == "phone" and step == "o_phone":
            d["step"] = "o_price"
            ctx.set_st(d)
            return show(ctx, "💼 Shartnoma summasi (so'm yoki $):", skip_kb("price"))
        elif arg == "price" and step == "o_price":
            edit("✔️ Narx keyinroq kiritiladi")
            return finish_order(ctx, d)
        else:
            return
        edit("⏭ O'tkazildi")
        return next_step(ctx, d)
    if cmd == "save":
        return save_tx(ctx, d)
    if cmd == "edit" and d and d.get("step") == "confirm":
        if arg == "amount":
            d.update(amount=None, orig=None, cur="UZS", rate=None, mr=False)
        if arg == "rate":
            d.update(rate=None, amount=None, mr=True)
        if arg == "category":
            d.update(
                cat=None,
                give=False,
                worker=None,
                pay=None,
                oa=bool(d.get("ord")),
                ca=bool(d.get("com")),
            )
        if arg == "order":
            d["oa"] = False
        api.clear_kb(ctx.chat, ctx.cb_msg)
        return next_step(ctx, d)
    # --- operations
    if cmd == "rcpt":
        op = Operation.objects.filter(number=int(arg)).first()
        if not op or not (ctx.admin or op.author_id == ctx.member.id):
            return send(ctx, "❗ Bu amalga chek qo'sha olmaysiz.")
        ctx.set_st({"step": "attach", "tx": int(arg)})
        return send(ctx, f"📎 #{arg} uchun chek rasmini yuboring.")
    if cmd == "del":
        return ask_delete(ctx, int(arg))
    if cmd == "delok":
        op = Operation.objects.select_related("member", "category").filter(number=int(arg)).first()
        if not S.can_delete(ctx.member, op):
            return edit("❗ O'chirib bo'lmadi.")
        deleted = S.delete_operation(op)
        edit(
            f"🗑 #{op.number} o'chirildi."
            + (" (o'tkazmaning ikkala tomoni)" if len(deleted) > 1 else "")
        )
        return announce_deleted(deleted, ctx.member.name)
    # --- views
    if cmd == "inf":
        return info(ctx, p[1], p[2], p[3] if len(p) > 3 else "x")
    if cmd == "ops":
        return ops(ctx, p[1], p[2], int(p[3]) if len(p) > 3 else 0)
    if cmd == "mon":
        return months_view(ctx, p[1])
    if cmd == "ocard":
        return order_card(ctx, arg)
    if cmd == "oclosed":
        from ..finance_models import ManualOrder

        rows = list(ManualOrder.objects.filter(is_closed=True)[:30])
        if not rows:
            return send(
                ctx, "Tugagan (qo'lda kiritilgan) buyurtma yo'q. Saytdagi buyurtmalar saytda."
            )
        return send(
            ctx,
            "📁 <b>Tugagan buyurtmalar</b>",
            ik([[b(f"{o.ref} · {o.client[:30]}", f"ocard:{o.ref}")] for o in rows]),
        )
    # --- month report
    if cmd == "msub" and d and d.get("step") == "month_confirm":
        api.clear_kb(ctx.chat, ctx.cb_msg)
        return month_submit(ctx, d)
    if cmd == "mnote" and d and d.get("step") == "month_confirm":
        d["step"] = "month_note"
        ctx.set_st(d)
        return send(ctx, "📝 Izohingizni yozing (masalan: «200 ming naqd rahbarga qaytardim»):")
    if cmd == "noexp":
        return edit("👍 Qabul qilindi. Rahmat!")
    if cmd == "trto":
        to = S.member_by_tg(arg)
        if not to or not to.has_wallet or to.pk == ctx.member.pk:
            return
        ctx.set_st({"step": "tr_amount", "to": to.telegram_id, "toName": to.name})
        return show(
            ctx, f"🔄 <b>{esc(to.name)}</b> ga qancha berdingiz? Summani yozing:", ik([[CANCEL]])
        )
    if cmd == "trok" and d and d.get("step") == "tr_confirm":
        return tr_save(ctx, d)
    if cmd == "go" and arg == "req":
        api.clear_kb(ctx.chat, ctx.cb_msg)
        return req_start(ctx)
    if cmd == "go":
        api.clear_kb(ctx.chat, ctx.cb_msg)
        return start_tx(ctx, OpKind.EXPENSE, ctx.member)
    if cmd in ("rq_ok", "rq_amt", "rq_no"):
        if not ctx.admin:
            return
        return req_answer(ctx, cmd, int(arg))

    if not ctx.admin:
        return
    # --- admin only
    if cmd == "onew":
        nid = S.next_manual_ref()
        ctx.set_st({"step": "o_id"})
        return send(
            ctx,
            f"🆕 Saytda yo'q buyurtma raqami: <b>{nid}</b>\nTugmani bosing yoki o'z raqamingizni yozing.\n<i>Saytdagi buyurtmalar avtomatik ko'rinadi — ularni bu yerda ochish shart emas.</i>",
            ik([[b(f"✅ {nid}", f"oid:{nid}")], [CANCEL]]),
        )
    if cmd == "oid" and d and d.get("step") == "o_id":
        d.update(oid=arg, step="o_client")
        ctx.set_st(d)
        return show(
            ctx,
            f"ID: <b>{esc(arg)}</b>\n\n👤 Mijoz ismi va buyurtma nomi:\n<i>masalan: Назира — oshxona mebeli</i>",
            ik([[CANCEL]]),
        )
    if cmd == "oimg":
        o = S.order_info(arg)
        if not o:
            return
        send(ctx, "⏳ Rasm tayyorlanmoqda…")
        return BN.send_ready_card(_bonus_or_temp(o), ctx.chat)
    if cmd == "oprice":
        ctx.set_st({"step": "o_newprice", "oid": arg})
        return send(ctx, f"💼 {esc(arg)} uchun shartnoma summasini yozing (so'm yoki $):")
    if cmd == "otoggle":
        o = S.order_info(arg)
        if not o or not o.manual:
            return
        mo = o.manual
        mo.is_closed = not mo.is_closed
        mo.closed = today() if mo.is_closed else None
        mo.save(update_fields=["is_closed", "closed"])
        if mo.is_closed:
            to_channel(
                f"✅ <b>Buyurtma yopildi:</b> {esc(mo.ref + ' · ' + mo.client)}\n🔴 Sarflandi: {money(S.order_stats(mo.ref)['spent'])}"
            )
        return order_card(ctx, mo.ref)
    if cmd == "give":
        u = S.member_by_tg(arg)
        if not u:
            return
        edit(f"💸 {esc(u.name)} ga")
        nd = {
            "t": "tx",
            "kind": OpKind.INCOME,
            "uid": u.telegram_id,
            "author": ctx.tg_id,
            "amount": None,
            "cur": "UZS",
            "orig": None,
            "rate": None,
            "cat": None,
            "ord": None,
            "com": None,
            "rcpt": None,
            "oa": True,
            "ca": False,
            "ra": True,
            "give": True,
        }
        return next_step(ctx, nd)
    if cmd == "who":
        return send(
            ctx,
            "👤 Kimning hamyoni?",
            ik(grid([b(u.name[:22], f"inf:{u.telegram_id}:{arg}:x") for u in S.wallets()], 2)),
        )
    if cmd == "xls":
        return send_excel(ctx, arg)
    if cmd == "nudge":
        u = S.member_by_tg(arg)
        r = api.send(
            arg,
            "🔔 Rahbar eslatmasi: iltimos, barcha kirim-chiqimlarni kiriting va kerak bo'lsa oylik hisobni topshiring.",
            kb_for(u),
        )
        return send(
            ctx,
            (
                "🔔 Eslatma yuborildi."
                if r.get("ok")
                else "❗ Yuborib bo'lmadi (xodim botni bloklagan bo'lishi mumkin)."
            ),
        )
    if cmd in ("approve", "reject"):
        u = S.member_by_tg(arg)
        if not u:
            return
        S.set_member_role(u, TelegramRole.STAFF if cmd == "approve" else TelegramRole.BLOCKED)
        edit(("✅ Qabul qilindi: " if cmd == "approve" else "🚫 Rad etildi: ") + esc(u.name))
        if cmd == "approve":
            api.send(
                u.telegram_id,
                "✅ Rahbar sizni tasdiqladi! Endi kirim-chiqimlarni kiritishingiz mumkin.\n\n"
                + HELP_STAFF,
                KB_STAFF,
            )
