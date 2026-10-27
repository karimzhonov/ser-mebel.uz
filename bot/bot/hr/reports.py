"""Text builders of the davomat reports, over the report DTOs of the backend
(hr/report_data.py). Port of the old hr/reports.py: the output is the same for the same data.
"""

from __future__ import annotations

from datetime import date

from .fmt import esc, fmt_day, fmt_min, month_name

MEDALS = ["🥇", "🥈", "🥉"]


def _names(items) -> str:
    return ", ".join(esc(x) for x in items)


# ------------------------------------------------------------------ day
def day_report(r: dict, title: str) -> str:
    """kind == live (today)."""
    day = date.fromisoformat(r["day"])
    L = [f"<b>{title}</b>", f"🗓 {fmt_day(day)}"]
    if r.get("empty"):
        return "\n".join(L + ["", "Bugun ishga kutilgan xodim yo'q (dam / bayram)."])
    on_time, late = r.get("on_time", []), r.get("late", [])
    waiting, absent, excused = r.get("waiting", []), r.get("absent", []), r.get("excused", [])
    expected = r.get("expected", 0)
    came = len(on_time) + len(late)
    pct = round(100 * len(on_time) / expected) if expected else 0
    L += [
        "",
        f"👥 Kutilgan: <b>{expected}</b> · Keldi: <b>{came}</b>",
        f"✅ Vaqtida: <b>{len(on_time)}</b> ({pct}%)",
        f"⏰ Kech qoldi: <b>{len(late)}</b>",
    ]
    if waiting:
        L.append(f"⏳ Hali kelmagan: <b>{len(waiting)}</b>")
    L.append(f"❌ Kelmadi: <b>{len(absent)}</b>")
    if excused:
        L.append(f"📝 Sababli kelmadi: <b>{len(excused)}</b>")
    if r.get("rest_count"):
        L.append(f"😴 Dam / ta'til: <b>{r['rest_count']}</b>")
    groups = r.get("groups") or []
    if groups:
        L += ["", "<b>🏢 Filiallar:</b>"]
        for g in groups:
            L.append(
                f"• {esc(g['title'])}: ✅{g['on_time']} ⏰{g['late']}"
                + (f" ⏳{g['waiting']}" if g["waiting"] else "")
                + f" ❌{g['absent']}"
                + (f" 📝{g['excused']}" if g["excused"] else "")
            )
    if late:
        tot = sum(x.get("late_min") or 0 for x in late)
        L += ["", f"<b>⏰ Kech qolganlar</b> (jami {fmt_min(tot)}):"]
        for i, x in enumerate(late, 1):
            why = (
                f" — {x['late_reason']}"
                + (f": {esc(x['late_comment'])}" if x.get("late_comment") else "")
                if x.get("late_reason")
                else " — sabab hali aytilmagan"
            )
            L.append(
                f"{i}. {esc(x['name'])} — {x['in_time']} (+{fmt_min(x.get('late_min'))}){why}"
            )
    if waiting:
        L += ["", "<b>⏳ Hali kelmaganlar:</b>"]
        for i, x in enumerate(waiting, 1):
            s = ""
            if x.get("eta"):
                s = f" — taxminan {x['eta']} da keladi"
            elif x.get("asked"):
                s = " — so'raldi, javob yo'q"
            elif x.get("can_dm") is False:
                s = " — botga ulanmagan"
            L.append(f"{i}. {esc(x['name'])}{s}")
    if absent:
        L += ["", "<b>❌ Kelmaganlar:</b>"]
        L += [
            f"{i}. {esc(x['name'])}" + (f" (aytgan vaqti {x['eta']})" if x.get("eta") else "")
            for i, x in enumerate(absent, 1)
        ]
    if excused:
        L += ["", "<b>📝 Sababli kelmaganlar:</b>"]
        L += [f"{i}. {esc(x['name'])} — {esc(x.get('note'))}" for i, x in enumerate(excused, 1)]
    leave = r.get("leave") or []
    if leave:
        L += [
            "",
            "<b>🏖 Ta'tilda:</b> "
            + ", ".join(f"{esc(x['name'])} ({esc(x.get('note'))})" for x in leave),
        ]
    if r.get("no_uniform"):
        L += ["", "<b>👕 Formasiz kelganlar:</b> " + _names(r["no_uniform"])]
    if on_time:
        L += [
            "",
            "<b>✅ Vaqtida kelganlar:</b> "
            + ", ".join(f"{esc(x['name'])} ({x['in_time']})" for x in on_time),
        ]
    early = r.get("yesterday_early") or []
    if early:
        L += ["", "<b>🚪 Kecha erta ketganlar:</b>"]
        L += [
            f"{i}. {esc(a['name'])} — {a['out_time']} ({fmt_min(a['early_min'])} erta)"
            f" — {a.get('early_reason') or 'Sababsiz'}"
            + (f": {esc(a['early_comment'])}" if a.get("early_comment") else "")
            for i, a in enumerate(early, 1)
        ]
    if r.get("yesterday_no_out"):
        L += [
            "",
            "<b>📭 Kecha ketish otchetini tashlamaganlar:</b> " + _names(r["yesterday_no_out"]),
        ]
    nc = r.get("not_connected") or []
    if nc:
        L += [
            "",
            f"⚠️ Botga ulanmaganlar ({len(nc)}): "
            + _names(nc)
            + "\nUlar botga /start bosmaguncha bot ularga yoza olmaydi.",
        ]
    return "\n".join(L)


def past_day_report(r: dict) -> str:
    """kind == past (a finished day)."""
    day = date.fromisoformat(r["day"])
    L = ["<b>📊 Hisobot</b>", f"🗓 {fmt_day(day)}", ""]
    if r.get("empty"):
        return "\n".join(L + ["Bu kun uchun ma'lumot yo'q."])
    L += [
        f"👥 Kutilgan: <b>{r['expected']}</b>",
        f"✅ Vaqtida: <b>{r['on_time']}</b>",
        f"⏰ Kech qoldi: <b>{r['late']}</b>",
        f"❌ Kelmadi: <b>{r['absent']}</b>",
        f"📝 Sababli kelmadi: <b>{r['excused']}</b>",
    ]
    rows = r.get("late_rows") or []
    if rows:
        L += ["", "<b>⏰ Kech qolganlar:</b>"]
        for i, a in enumerate(rows, 1):
            L.append(
                f"{i}. {esc(a['name'])} — {a['in_time']} (+{fmt_min(a['late_min'])})"
                + (
                    f" — {a['late_reason']}"
                    + (f": {esc(a['late_comment'])}" if a.get("late_comment") else "")
                    if a.get("late_reason")
                    else ""
                )
            )
    if r.get("absent_names"):
        L += ["", "<b>❌ Kelmaganlar:</b> " + _names(r["absent_names"])]
    return "\n".join(L)


def render_day(r: dict, title: str) -> str:
    return day_report(r, title) if r.get("kind") == "live" else past_day_report(r)


# ------------------------------------------------------------------ period / ranking
def period_report(r: dict, title: str) -> str:
    L = [f"<b>{title}</b>", f"🗓 {r['date_from']} — {r['date_to']}", ""]
    if r.get("empty"):
        return "\n".join(L + ["Hali ma'lumot yo'q."])
    rows = r["rows"]
    L += [
        f"✅ Vaqtida: <b>{r['on_time']}</b> · ⏰ Kech: <b>{r['late']}</b> "
        f"(sababli {r['late_reasoned']}) · ❌ Kelmadi: <b>{r['absent']}</b> · "
        f"📝 Sababli: <b>{r['excused']}</b>",
        f"📈 Umumiy intizom: <b>{r['discipline']}%</b>",
        f"⌛ Jami kechikish: <b>{fmt_min(r['late_min'])}</b>",
        "",
        "<b>Xodimlar reytingi</b> (ball · vaqtida / kech / kelmadi / erta ketdi · intizom):",
    ]
    for i, s in enumerate(rows):
        medal = MEDALS[i] if i < 3 else f"{i + 1}."
        L.append(
            f"{medal} {esc(s['name'])}: <b>{s['pts']}</b> ball · {s['on_time']} / {s['late']} / "
            f"{s['absent']} / {s['early_n']} · {s['disc']}%"
            + (f", kechikish {fmt_min(s['late_min'])}" if s["late_min"] else "")
        )
    worst = sorted(
        [s for s in rows if s["viol"]],
        key=lambda s: (-((s["late"] - s["late_r"]) + 2 * s["absent"]), -s["late_min"]),
    )
    if worst:
        L += [
            "",
            "<b>⚠️ E'tibor talab qiladi:</b> "
            + ", ".join(
                f"{esc(s['name'])} ({s['late'] - s['late_r']} sababsiz kech, {s['absent']} kelmadi"
                + (f", {s['early_n']} erta ketdi" if s["early_n"] else "")
                + ")"
                for s in worst[:5]
            ),
        ]
    return "\n".join(L)


def ranking_text(rows: list[dict], title: str) -> str:
    L = [f"<b>{title}</b>", ""]
    if not rows:
        return "\n".join(L + ["Hali ma'lumot yo'q."])
    for i, s in enumerate(rows):
        medal = MEDALS[i] if i < 3 else f"{i + 1}."
        L.append(
            f"{medal} {esc(s['name'])} — <b>{s['pts']}</b> ball (intizom {s['disc']}%"
            + (f", +{s['bonus']} bonus" if s.get("bonus") else "")
            + (f", rahbardan {s['adj']:+d}" if s.get("adj") else "")
            + ")"
        )
    return "\n".join(L + ["", "Qoidalar: /ballar"])


def month_winner_text(ym: str, rows: list[dict]) -> str:
    """The «Oy xodimi» pick message (rows: active employees with expected days)."""
    t = ranking_text(rows, f"🏆 Oy xodimi tanlovi — {month_name(ym)}")
    if not rows:
        return t
    return (
        t
        + f"\n\nBallar bo'yicha g'olib: <b>{esc(rows[0]['name'])}</b>. "
        "Guruhlarda kimni «Oy xodimi» deb e'lon qilamiz?"
    )


def year_report(y: str, rows: list[dict]) -> str:
    L = [f"<b>👑 Yil xodimi tanlovi — {y}</b>", ""]
    if not rows:
        return "\n".join(L + ["Hali ma'lumot yo'q."])
    for i, s in enumerate(rows):
        medal = MEDALS[i] if i < 3 else f"{i + 1}."
        L.append(
            f"{medal} {esc(s['name'])} — <b>{s['pts']}</b> ball, intizom {s['disc']}%"
            + (f", 🏆×{s['wins']} oy xodimi" if s.get("wins") else "")
        )
    L += ["", "Guruhlarda kimni «Yil xodimi» deb e'lon qilamiz?"]
    return "\n".join(L)
