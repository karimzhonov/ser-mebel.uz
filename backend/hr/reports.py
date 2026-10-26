"""Text reports for Telegram (dayReport_, pastDayReport_, periodReport_, …)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape

from accounting.telegram.api import b, ik

from . import services as S
from .models import Attendance, Winner


def esc(v) -> str:
    return escape("" if v is None else str(v), quote=False)


def _summarize(rows):
    s = {
        k: []
        for k in ("on_time", "late", "waiting", "absent", "excused", "rest", "no_uni", "not_conn")
    }
    s["expected"] = 0
    for r in rows:
        (
            s[r.st] if r.st in ("on_time", "late", "waiting", "absent", "excused") else s["rest"]
        ).append(r)
        if r.st in ("on_time", "late", "waiting", "absent", "excused"):
            s["expected"] += 1
        if r.g("uniform") is False:
            s["no_uni"].append(r)
        if r.e.can_dm is False and r.e.is_active:
            s["not_conn"].append(r.e)
    s["late"].sort(key=lambda r: -(r.g("late_min") or 0))
    return s


def day_report(day: date, now_d: datetime, title: str) -> str:
    rows = S.compute_day(day, now_d)
    s = _summarize(rows)
    L = [f"<b>{title}</b>", f"🗓 {S.fmt_day(day)}"]
    if not s["expected"] and not s["on_time"] and not s["late"]:
        return "\n".join(L + ["", "Bugun ishga kutilgan xodim yo'q (dam / bayram)."])
    came = len(s["on_time"]) + len(s["late"])
    pct = round(100 * len(s["on_time"]) / s["expected"]) if s["expected"] else 0
    L += [
        "",
        f"👥 Kutilgan: <b>{s['expected']}</b> · Keldi: <b>{came}</b>",
        f"✅ Vaqtida: <b>{len(s['on_time'])}</b> ({pct}%)",
        f"⏰ Kech qoldi: <b>{len(s['late'])}</b>",
    ]
    if s["waiting"]:
        L.append(f"⏳ Hali kelmagan: <b>{len(s['waiting'])}</b>")
    L.append(f"❌ Kelmadi: <b>{len(s['absent'])}</b>")
    if s["excused"]:
        L.append(f"📝 Sababli kelmadi: <b>{len(s['excused'])}</b>")
    if s["rest"]:
        L.append(f"😴 Dam / ta'til: <b>{len(s['rest'])}</b>")
    groups = S.groups()
    if len(groups) > 1:
        L += ["", "<b>🏢 Filiallar:</b>"]
        for g in groups:
            gr = [r for r in rows if r.e.group_id == g.id]
            if not gr:
                continue
            gs = _summarize(gr)
            L.append(
                f"• {esc(g.title)}: ✅{len(gs['on_time'])} ⏰{len(gs['late'])}"
                + (f" ⏳{len(gs['waiting'])}" if gs["waiting"] else "")
                + f" ❌{len(gs['absent'])}"
                + (f" 📝{len(gs['excused'])}" if gs["excused"] else "")
            )
    if s["late"]:
        tot = sum(r.g("late_min") or 0 for r in s["late"])
        L += ["", f"<b>⏰ Kech qolganlar</b> (jami {S.fmt_min(tot)}):"]
        for i, r in enumerate(s["late"], 1):
            why = (
                f" — {r.g('late_reason')}"
                + (f": {esc(r.g('late_comment'))}" if r.g("late_comment") else "")
                if r.g("late_reason")
                else " — sabab hali aytilmagan"
            )
            L.append(
                f"{i}. {esc(r.e.name)} — {S.hm(r.g('in_time'))} (+{S.fmt_min(r.g('late_min'))}){why}"
            )
    if s["waiting"]:
        L += ["", "<b>⏳ Hali kelmaganlar:</b>"]
        for i, r in enumerate(s["waiting"], 1):
            x = ""
            if r.g("eta"):
                x = f" — taxminan {S.hm(r.g('eta'))} da keladi"
            elif r.g("asked"):
                x = " — so'raldi, javob yo'q"
            elif r.e.can_dm is False:
                x = " — botga ulanmagan"
            L.append(f"{i}. {esc(r.e.name)}{x}")
    if s["absent"]:
        L += ["", "<b>❌ Kelmaganlar:</b>"]
        L += [
            f"{i}. {esc(r.e.name)}" + (f" (aytgan vaqti {S.hm(r.g('eta'))})" if r.g("eta") else "")
            for i, r in enumerate(s["absent"], 1)
        ]
    if s["excused"]:
        L += ["", "<b>📝 Sababli kelmaganlar:</b>"]
        L += [f"{i}. {esc(r.e.name)} — {esc(r.note)}" for i, r in enumerate(s["excused"], 1)]
    lv = [r for r in s["rest"] if r.st == "leave"]
    if lv:
        L += ["", "<b>🏖 Ta'tilda:</b> " + ", ".join(f"{esc(r.e.name)} ({esc(r.note)})" for r in lv)]
    if s["no_uni"]:
        L += ["", "<b>👕 Formasiz kelganlar:</b> " + ", ".join(esc(r.e.name) for r in s["no_uni"])]
    if s["on_time"]:
        ot = sorted(s["on_time"], key=lambda r: S.hm(r.g("in_time")))
        L += [
            "",
            "<b>✅ Vaqtida kelganlar:</b> "
            + ", ".join(f"{esc(r.e.name)} ({S.hm(r.g('in_time'))})" for r in ot),
        ]
    yd = day - timedelta(days=1)
    yrows = list(
        Attendance.objects.filter(day=yd, in_time__isnull=False).select_related("employee")
    )
    early = [a for a in yrows if a.out_time and a.early_min]
    no_out = [a for a in yrows if not a.out_time]
    if early:
        L += ["", "<b>🚪 Kecha erta ketganlar:</b>"]
        L += [
            f"{i}. {esc(a.employee.name)} — {S.hm(a.out_time)} ({S.fmt_min(a.early_min)} erta) — {a.early_reason or 'Sababsiz'}"
            + (f": {esc(a.early_comment)}" if a.early_comment else "")
            for i, a in enumerate(early, 1)
        ]
    if no_out:
        L += [
            "",
            "<b>📭 Kecha ketish otchetini tashlamaganlar:</b> "
            + ", ".join(esc(a.employee.name) for a in no_out),
        ]
    if s["not_conn"]:
        L += [
            "",
            f"⚠️ Botga ulanmaganlar ({len(s['not_conn'])}): "
            + ", ".join(esc(e.name) for e in s["not_conn"])
            + "\nUlar botga /start bosmaguncha bot ularga yoza olmaydi.",
        ]
    return "\n".join(L)


def past_day_report(day: date) -> str:
    rows = list(Attendance.objects.filter(day=day, finalized=True).select_related("employee"))
    L = ["<b>📊 Hisobot</b>", f"🗓 {S.fmt_day(day)}", ""]
    if not rows:
        return "\n".join(L + ["Bu kun uchun ma'lumot yo'q."])

    def by(st):
        return [a for a in rows if a.status == st]

    exp = len([a for a in rows if a.status in ("on_time", "late", "absent", "excused")])
    L += [
        f"👥 Kutilgan: <b>{exp}</b>",
        f"✅ Vaqtida: <b>{len(by('on_time'))}</b>",
        f"⏰ Kech qoldi: <b>{len(by('late'))}</b>",
        f"❌ Kelmadi: <b>{len(by('absent'))}</b>",
        f"📝 Sababli kelmadi: <b>{len(by('excused'))}</b>",
    ]
    if by("late"):
        L += ["", "<b>⏰ Kech qolganlar:</b>"]
        for i, a in enumerate(sorted(by("late"), key=lambda a: -(a.late_min or 0)), 1):
            L.append(
                f"{i}. {esc(a.employee.name)} — {S.hm(a.in_time)} (+{S.fmt_min(a.late_min)})"
                + (
                    f" — {a.late_reason}" + (f": {esc(a.late_comment)}" if a.late_comment else "")
                    if a.late_reason
                    else ""
                )
            )
    if by("absent"):
        L += ["", "<b>❌ Kelmaganlar:</b> " + ", ".join(esc(a.employee.name) for a in by("absent"))]
    return "\n".join(L)


def period_report(start: date, end: date, now_d: datetime, title: str) -> str:
    today = now_d.date()
    st = S.period_stats(start, end, now_d)
    L = [f"<b>{title}</b>", f"🗓 {start} — {min(end, today)}", ""]
    if not st:
        return "\n".join(L + ["Hali ma'lumot yo'q."])
    exp, on = sum(s.exp for s in st), sum(s.on_time for s in st)
    L += [
        f"✅ Vaqtida: <b>{on}</b> · ⏰ Kech: <b>{sum(s.late for s in st)}</b> (sababli {sum(s.late_r for s in st)}) · "
        f"❌ Kelmadi: <b>{sum(s.absent for s in st)}</b> · 📝 Sababli: <b>{sum(s.excused for s in st)}</b>",
        f"📈 Umumiy intizom: <b>{round(100 * on / exp) if exp else 100}%</b>",
        f"⌛ Jami kechikish: <b>{S.fmt_min(sum(s.late_min for s in st))}</b>",
        "",
        "<b>Xodimlar reytingi</b> (ball · vaqtida / kech / kelmadi / erta ketdi · intizom):",
    ]
    for i, s in enumerate(st):
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i + 1}."
        L.append(
            f"{medal} {esc(s.e.name)}: <b>{s.pts}</b> ball · {s.on_time} / {s.late} / {s.absent} / {s.early_n} · {s.disc}%"
            + (f", kechikish {S.fmt_min(s.late_min)}" if s.late_min else "")
        )
    worst = sorted(
        [s for s in st if s.viol],
        key=lambda s: (-((s.late - s.late_r) + 2 * s.absent), -s.late_min),
    )
    if worst:
        L += [
            "",
            "<b>⚠️ E'tibor talab qiladi:</b> "
            + ", ".join(
                f"{esc(s.e.name)} ({s.late - s.late_r} sababsiz kech, {s.absent} kelmadi"
                + (f", {s.early_n} erta ketdi" if s.early_n else "")
                + ")"
                for s in worst[:5]
            ),
        ]
    return "\n".join(L)


def ranking_text(st, title: str) -> str:
    L = [f"<b>{title}</b>", ""]
    if not st:
        return "\n".join(L + ["Hali ma'lumot yo'q."])
    for i, s in enumerate(st):
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i + 1}."
        L.append(
            f"{medal} {esc(s.e.name)} — <b>{s.pts}</b> ball (intizom {s.disc}%"
            + (f", +{s.bonus} bonus" if s.bonus else "")
            + (f", rahbardan {s.adj:+d}" if s.adj else "")
            + ")"
        )
    return "\n".join(L + ["", "Qoidalar: /ballar"])


def month_winner_msg(ym: str, now_d: datetime) -> tuple[str, dict | None]:
    st = [s for s in S.month_stats(ym, now_d) if s.e.is_active and s.exp]
    t = ranking_text(st, f"🏆 Oy xodimi tanlovi — {S.month_name(ym)}")
    if not st:
        return t, None
    t += f"\n\nBallar bo'yicha g'olib: <b>{esc(st[0].e.name)}</b>. Guruhlarda kimni «Oy xodimi» deb e'lon qilamiz?"
    kb = ik(
        [
            [
                b(
                    f"{['🥇', '🥈', '🥉'][i]} {s.e.name} — e'lon qilish",
                    f"dv:ann:m:{ym}:{s.e.telegram_id}",
                )
            ]
            for i, s in enumerate(st[:3])
        ]
    )
    return t, kb


def year_report(y: str, now_d: datetime) -> tuple[str, dict | None]:
    st = S.year_stats(y, now_d)
    L = [f"<b>👑 Yil xodimi tanlovi — {y}</b>", ""]
    if not st:
        return "\n".join(L + ["Hali ma'lumot yo'q."]), None
    for i, s in enumerate(st):
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i + 1}."
        L.append(
            f"{medal} {esc(s['e'].name)} — <b>{s['pts']}</b> ball, intizom {s['disc']}%"
            + (f", 🏆×{s['wins']} oy xodimi" if s["wins"] else "")
        )
    L += ["", "Guruhlarda kimni «Yil xodimi» deb e'lon qilamiz?"]
    kb = ik(
        [
            [
                b(
                    f"{['🥇', '🥈', '🥉'][i]} {s['e'].name} — e'lon qilish",
                    f"dv:ann:y:{y}:{s['e'].telegram_id}",
                )
            ]
            for i, s in enumerate(st[:3])
        ]
    )
    return "\n".join(L), kb


def winner_exists(kind: str, period: str) -> bool:
    return Winner.objects.filter(kind=kind, period=period).exists()
