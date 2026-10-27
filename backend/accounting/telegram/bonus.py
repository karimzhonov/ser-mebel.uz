"""Order follow-up of the finance bot (siteNotify_ and friends in code.txt):
deadline reminders, the «Готов» payment sheet, bonus tracking, warranty letters,
client feedback and «Saytga kiritish» tasks.

The Apps Script scraped /admin/ every hour to see statuses; here the same checks read
order.Order directly and run from the scheduler (accounting/jobs.py).
"""

from __future__ import annotations

import logging
from datetime import date
from urllib.parse import quote

from constance import config

from oauth.models import TelegramMember

from .. import services as S
from ..images import report_card_png
from ..text import cur_name, days_between, ddmm, esc, fmt_cur, money, num, today
from ..models import ClientFeedback, OrderBonus, SiteEntryTask
from . import api
from .api import b, ik
from .notify import notify_to, to_admins

log = logging.getLogger("finance.bonus")


def receivers():
    return S.duty_members("is_bonus_receiver")


def deadline_people():
    return S.duty_members("is_deadline_receiver")


def is_receiver(m: TelegramMember) -> bool:
    return m.is_admin or m.is_bonus_receiver


# ------------------------------------------------------------------ hisob-kitob varaqasi
def card_values(bn: OrderBonus, paid) -> dict:
    rest = max(S.ZERO, bn.total - paid)
    c = bn.currency
    return {
        "MIJOZ": f"{bn.client[:26]} (ID {bn.order_ref})",
        "TUR": (bn.description or "—")[:34],
        "SANA": ddmm(bn.ready_date),
        "VAL": f"Summa ({cur_name(c)})",
        "S1": fmt_cur(bn.total, c),
        "S2": "- " + fmt_cur(paid, c),
        "S3": fmt_cur(rest, c),
        "FORMULA": f"{fmt_cur(bn.total, c)} – {fmt_cur(paid, c)} =",
        "YAKUN": f"{fmt_cur(rest, c)} {cur_name(c)}",
    }


def bonus_line(bn: OrderBonus) -> str:
    if not bn.total:
        return ""
    som = bn.total * S.usd_rate() if bn.currency == "USD" else bn.total
    return (
        "🎁 <b>Bonus</b> (to'liq yopilsa): 3 kun ichida 0.5% (≈"
        + num(som * S.D("0.005"))
        + " so'm), 7 kungacha 0.4%, 30 kungacha 0.3%, keyin 0%."
    )


def ready_text(bn: OrderBonus, ms: dict) -> str:
    c = bn.currency
    if bn.total:
        money_part = (
            f"\n💼 Umumiy summa: <b>{fmt_cur(bn.total, c)} {cur_name(c)}</b>"
            f"\n💰 To'langan ({'saytdan' if ms['src'] == 'sayt' else 'botdan'}): {fmt_cur(ms['paid'], c)}"
            f"\n🧮 Qoldiq: <b>{fmt_cur(ms['rest'], c)} {cur_name(c)}</b>"
        )
    else:
        money_part = "\n⚠️ Saytda buyurtma summasi kiritilmagan."
    return (
        f"✅ <b>Zakaz tayyor (Готов)</b>\n🧾 <b>{esc(bn.order_ref)} · {esc(bn.client)}</b>"
        + money_part
        + "\n\n❗ <b>Menejerlardan so'rang: yana pul qo'shilmaganmi?</b> (qo'shimcha ish, o'zgarish, skidka)\n\n"
        + bonus_line(bn)
        + "\n\n<i>Mijozdan pulni olganingizda «💰 Pul oldim» ni bosing: to'liq yoki qisman. To'liq olingan kun bo'yicha bonus hisoblanadi.</i>"
    )


def send_ready_card(bn: OrderBonus, to_chat=None, test=False):
    """sendReadyCard_: to the bonus receivers (or, from the order card, to one chat)."""
    ms = S.money_state(bn)
    try:
        png = report_card_png(card_values(bn, ms["paid"]))
    except Exception:  # noqa: BLE001
        log.exception("report card")
        png = None
    text = ready_text(bn, ms)
    if to_chat and test:
        kb = ik([[b("💰 Pul oldim", "tst:pul")], [b("📜 Kafolat xati berdim", "tst:kfx")]])
        api.send(to_chat, "🧪 <b>TEST</b> — bonus oluvchiga aynan quyidagi xabar boradi:")
        if png and api.send_photo(to_chat, png, text, kb).get("ok"):
            return
        return api.send(to_chat, text, kb)
    if to_chat:
        if png and api.send_photo(to_chat, png, text).get("ok"):
            return
        return api.send(to_chat, text)
    kb = ik(
        [
            [b("💰 Pul oldim", f"bpaid:{bn.order_ref}")],
            [b("📜 Kafolat xati berdim", f"kfx:{bn.order_ref}")],
        ]
    )
    notify_to(receivers(), "«Готов» bonus oluvchi", text, png, kb)


def paid_kb(ref: str):
    return ik([[b("💰 Pul oldim", f"bpaid:{ref}")]])


# ------------------------------------------------------------------ bonus progress
def bonus_check(ref: str, ok_hour: bool):
    """bonusCheck_: rest reached 0 → ask the receiver to close; after 30 days → no
    bonus; day 2/6/29 → «tomorrow the N-day term ends» reminders."""
    bn = OrderBonus.objects.filter(order_ref=str(ref), status="waiting").first()
    if not bn:
        return
    d = days_between(bn.ready_date, today())
    rest = None
    if bn.total > 0:
        ms = S.money_state(bn)
        rest = ms["rest"]
        if rest != bn.rest:
            bn.rest = rest
            bn.save(update_fields=["rest", "updated_at"])
        if rest <= S.bonus_tolerance(bn.currency):
            if not bn.zero_notified and ok_hour:
                bn.zero_notified = today()
                bn.save(update_fields=["zero_notified", "updated_at"])
                notify_to(
                    receivers(),
                    "«Готов» bonus oluvchi",
                    f"✅ <b>{esc(bn.order_ref)} · {esc(bn.client)}</b>\n🧮 Qoldiq 0 "
                    f"({'saytda' if ms['src'] == 'sayt' else 'botda'}). Zakazni yopasizmi? "
                    f"Bonus: <b>{S.bonus_percent(max(0, d))}%</b> ({max(0, d)} kun)",
                    None,
                    ik([[b("✅ Zakazni yopish", f"bpok:{bn.order_ref}")]]),
                )
            return
    if d > 30:
        S.bonus_expire(bn, rest)
        return
    if not ok_hour or not bn.total:
        return
    for day, key, label, pct in [
        (2, "d3", "3 kunlik", "0.5"),
        (6, "d7", "7 kunlik", "0.4"),
        (29, "d30", "30 kunlik", "0.3"),
    ]:
        if d != day or bn.reminders.get(key):
            continue
        bn.reminders[key] = today().isoformat()
        bn.save(update_fields=["reminders", "updated_at"])
        notify_to(
            receivers(),
            "«Готов» bonus oluvchi",
            f"⏳ <b>Ertaga {label} muddat tugaydi</b>\n🧾 {esc(bn.order_ref)} · {esc(bn.client)}"
            f"\n🧮 Qoldiq: <b>{fmt_cur(rest, bn.currency)} {cur_name(bn.currency)}</b>"
            f"\n🎁 Bugun-ertaga to'liq yopilsa — {pct}% bonus."
            "\n\n❗ Menejerlardan so'rang: yana pul qo'shilmaganmi?\n<i>Pulni olganingizda «💰 Pul oldim» ni bosing.</i>",
            None,
            paid_kb(bn.order_ref),
        )


def announce_bonus_done(bn: OrderBonus):
    t = (
        f"🎉 <b>{esc(bn.order_ref)} · {esc(bn.client)}</b> — mijozdan pul to'liq olindi ({bn.days} kunda)"
        f"\n🎁 Bonus: <b>{(bn.percent or 0).normalize()}% = {money(bn.bonus or 0)}</b>\n📝 {esc(bn.note)}"
        + (
            "\n<i>«Bonuslar» bo'limiga yozildi. Saytda qoldiqni ham tekshirib qo'ying.</i>"
            if bn.percent
            else "\n<i>30 kundan o'tgani uchun bonus yo'q.</i>"
        )
    )
    rec = receivers()
    fb = notify_to(rec, "«Готов» bonus oluvchi", t)
    if not fb:
        ids = {m.pk for m in rec}
        for a in S.admins():
            if a.pk not in ids:
                api.send(a.telegram_id, t)


# ------------------------------------------------------------------ site entry / feedback
def site_entry_notify(task: SiteEntryTask, collector_name: str):
    text = (
        f"🌐 <b>Saytga kiriting</b>\n🧾 <b>{esc(task.order_ref)} · {esc(task.client)}</b>"
        f"\n💰 {esc(collector_name)} mijozdan oldi: <b>{esc(task.sum_text)}</b>\n🧮 Yangi qoldiq: <b>{esc(task.rest_text)}</b>"
        "\n\nSaytda shu zakazning «Полученная сумма» ni to'g'rilang, keyin tugmani bosing."
    )
    notify_to(
        S.duty_members("is_site_entry"),
        "Saytga kirituvchi menejer",
        text,
        None,
        ik([[b("✅ Saytga kiritdim", f"skt:{task.code}")]]),
    )


def site_entry_done_announce(task: SiteEntryTask, by_name: str):
    to_admins(
        f"🌐 ✅ <b>{esc(by_name)}</b> saytga kiritdi\n🧾 <b>{esc(task.order_ref)} · {esc(task.client)}</b>"
        f"\n💰 {esc(task.sum_text)} ({esc(task.taken_by)} olgan)\n🧮 Qoldiq: {esc(task.rest_text)}"
    )


def feedback_kb(ref: str):
    return ik([[b("📝 Fikr oldim", f"fko:{ref}")]])


def feedback_check(ok_hour: bool):
    """fikrCheck_: 3 days after Готов ask the feedback manager; remind after 2 more."""
    if not ok_hour:
        return
    t = today()
    for fb in ClientFeedback.objects.exclude(status="received"):
        if fb.status == "scheduled":
            if not fb.ready_date or days_between(fb.ready_date, t) < 3:
                continue
            fb.status, fb.asked_date = "asked", t
            fb.save(update_fields=["status", "asked_date"])
            notify_to(
                S.duty_members("is_feedback"),
                "Mijoz fikri menejeri",
                f"💬 <b>Mijoz fikrini bilish kerak</b>\n🧾 <b>{esc(fb.order_ref)} · {esc(fb.client)}</b>"
                + (f"\n📞 {esc(fb.phone)}" if fb.phone else "")
                + f"\n📅 Готов: {ddmm(fb.ready_date)} (3 kun o'tdi)\n\nMijozga qo'ng'iroq qiling yoki yozing, fikrini oling. "
                "Keyin «📝 Fikr oldim» ni bosib, <b>skrinshot</b> yuboring.",
                None,
                feedback_kb(fb.order_ref),
            )
        elif (
            fb.status == "asked"
            and not fb.reminded
            and fb.asked_date
            and days_between(fb.asked_date, t) >= 2
        ):
            fb.reminded = t
            fb.save(update_fields=["reminded"])
            notify_to(
                S.duty_members("is_feedback"),
                "Mijoz fikri menejeri",
                f"⏰ <b>Eslatma: mijoz fikri hali olinmagan</b>\n🧾 <b>{esc(fb.order_ref)} · {esc(fb.client)}</b>"
                + (f"\n📞 {esc(fb.phone)}" if fb.phone else ""),
                None,
                feedback_kb(fb.order_ref),
            )


def site_entry_remind(ok_hour: bool):
    if not ok_hour:
        return
    t = today()
    for task in SiteEntryTask.objects.filter(is_done=False, reminded__isnull=True):
        if days_between(task.date, t) < 1:
            continue
        task.reminded = t
        task.save(update_fields=["reminded"])
        notify_to(
            S.duty_members("is_site_entry"),
            "Saytga kirituvchi menejer",
            f"⏰ <b>Eslatma: saytga hali kiritilmagan</b>\n🧾 <b>{esc(task.order_ref)} · {esc(task.client)}</b>"
            f"\n💰 {esc(task.sum_text)}\n🧮 Qoldiq: {esc(task.rest_text)}",
            None,
            ik([[b("✅ Saytga kiritdim", f"skt:{task.code}")]]),
        )


# ------------------------------------------------------------------ the hourly order pass
def bonus_since() -> date:
    """Only orders that became Готов after the bot moved here get a card (the Apps
    Script kept BONUS_BASE for the same reason). Set once, editable in settings."""
    raw = str(config.FIN_BONUS_SINCE or "").strip()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        d = today()
        config.FIN_BONUS_SINCE = d.isoformat()
        return d


def deadline_reminders(infos):
    """Srok: 7 and 1 days left → deadline people; 3 days left → also the bonus
    receivers, with the address and a map link."""
    t = today()
    for info in infos:
        if not info.end_date or info.bucket in ("yakun", "tugadi"):
            continue
        left = days_between(t, info.end_date)
        key = "7" if 3 < left <= 7 else "3" if 1 < left <= 3 else "1" if 0 <= left <= 1 else ""
        if not key or not S.once(f"srk:{info.ref}:{key}:{info.end_date.isoformat()}"):
            continue
        head = (
            f"🧾 <b>{esc(info.ref)} · {esc(info.client)}</b>\n📅 Topshirish sanasi: <b>{ddmm(info.end_date)}</b>"
            + (f"\n📌 Holat: {esc(info.status_label)}" if info.status_label else "")
        )
        left_txt = "bugun" if left == 0 else f"{left} kun qoldi"
        if key == "3":
            q = quote(f"{info.address or info.client}, Toshkent")
            text = (
                f"📍 <b>Srok: {left_txt}</b>\n{head}\n📞 Telefon: {esc(info.phone or '—')}\n🏠 Manzil: {esc(info.address or '—')}"
                f'\n🗺 <a href="https://www.google.com/maps/search/?api=1&query={q}">Xaritada ochish</a>'
            )
            people = {m.pk: m for m in receivers() + deadline_people()}
            notify_to(list(people.values()), "Srok va bonus xodimlari", text)
        else:
            notify_to(
                deadline_people(),
                "Srok xodimi",
                f"⏰ <b>Srok yaqinlashmoqda — {left_txt}</b>\n{head}",
            )


def new_ready_orders(infos, ok_hour: bool):
    """A new «Готов» → payment sheet to the bonus receiver, bonus tracking starts,
    warranty row and a feedback task are created. At most 5 per pass, daytime only."""
    if not ok_hour:
        return
    since = bonus_since()
    sent = 0
    for info in infos:
        if info.bucket not in ("yakun", "tugadi") or not info.ready_date or info.ready_date < since:
            continue
        if OrderBonus.objects.filter(order_ref=info.ref).exists():
            continue
        if sent >= 5:
            break
        sent += 1
        bn, _ = S.bonus_start(info, info.ready_date)
        try:
            send_ready_card(bn)
        except Exception:  # noqa: BLE001
            log.exception("ready card %s", info.ref)
        S.warranty_ensure(info.ref, info.client, info.ready_date)
        S.feedback_schedule(info, info.ready_date)


def hourly_orders(ok_hour: bool):
    infos = S.open_orders(["jarayonda", "yangi", "kutish", "yakun"])
    deadline_reminders(infos)
    new_ready_orders(infos, ok_hour)
    for bn in OrderBonus.objects.filter(status="waiting"):
        info = S.order_info(bn.order_ref)
        if (
            info
            and info.order
            and info.total
            and not bn.rest_base
            and (bn.total != info.total or bn.currency != info.currency)
        ):
            bn.total, bn.currency = info.total, info.currency
            bn.save(update_fields=["total", "currency", "updated_at"])
        try:
            bonus_check(bn.order_ref, ok_hour)
        except Exception:  # noqa: BLE001
            log.exception("bonus check %s", bn.order_ref)
    feedback_check(ok_hour)
    site_entry_remind(ok_hour)
