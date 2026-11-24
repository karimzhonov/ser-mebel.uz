"""The printable salary sheet (A4), drawn from payroll.services.sheet_view() — the same
data the page shows, so the paper and the screen never disagree. The layout follows
the office Excel templates: header, the kind's sections, advances, the final sum and
signatures. A sheet that is not approved yet is stamped «QORALAMA»."""

from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONTS = Path(__file__).resolve().parents[1] / "accounting" / "fonts"
NAVY = colors.HexColor("#1F3864")
SOFT = colors.HexColor("#EEF2F8")
LINE = colors.HexColor("#C9D3E3")
WIDTH = A4[0] - 24 * mm

_fonts = False


def _register() -> None:
    global _fonts
    if not _fonts:
        pdfmetrics.registerFont(TTFont("Mont", str(FONTS / "Montserrat-Regular.ttf")))
        pdfmetrics.registerFont(TTFont("Mont-Bold", str(FONTS / "Montserrat-Bold.ttf")))
        _fonts = True


def _st(size=8.5, bold=False, align=0, color=colors.black) -> ParagraphStyle:
    return ParagraphStyle(
        "x",
        fontName="Mont-Bold" if bold else "Mont",
        fontSize=size,
        leading=size * 1.3,
        alignment=align,
        textColor=color,
    )


def _esc(s) -> str:
    return str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def P(text, **kw) -> Paragraph:
    return Paragraph(_esc(text), _st(**kw))


def money(v) -> str:
    n = Decimal(str(v or 0))
    s = f"{abs(n):,.0f}".replace(",", " ")
    return f"−{s}" if n < 0 else s


def usd(v) -> str:
    n = Decimal(str(v or 0))
    return f"{n:,.2f}".replace(",", " ").rstrip("0").rstrip(".") + " $"


def ddmm(iso: str | None) -> str:
    if not iso:
        return ""
    y, m, d = iso[:10].split("-")
    return f"{d}.{m}.{y}"


def _grid(rows, widths, head=True, bold_last=False) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1 if head else 0)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]
    if head:
        style.append(("BACKGROUND", (0, 0), (-1, 0), SOFT))
    if bold_last:
        style.append(("BACKGROUND", (0, -1), (-1, -1), SOFT))
    t.setStyle(TableStyle(style))
    return t


def _title(text: str) -> Table:
    t = Table([[P(text, bold=True, color=colors.white, size=9)]], colWidths=[WIDTH])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return t


R = {"align": TA_RIGHT}


def _section(sec: dict, lines: list[dict]) -> list:
    key = sec["key"]
    rows = [ln for ln in lines if ln["section"] == key]
    out = [Spacer(1, 3 * mm), _title(sec["title"])]
    if key in ("job", "car"):
        body = [[P("№", bold=True), P("ID", bold=True), P("Mijoz / ish nomi", bold=True), P("Summa (so'm)", bold=True, **R)]]
        for i, ln in enumerate(rows, 1):
            body.append([P(i), P(ln["order_ref"]), P(ln["title"]), P(money(ln["value"]), **R)])
        body.append(["", "", P("JAMI", bold=True), P(money(sec["total"]), bold=True, **R)])
        out.append(_grid(body, [10 * mm, 22 * mm, WIDTH - 72 * mm, 40 * mm], bold_last=True))
    elif key in ("taken", "delivered"):
        body = [[P("№", bold=True), P("ID", bold=True), P("Mijoz / ish nomi", bold=True), P("Zakaz ($)", bold=True, **R), P("Foiz", bold=True, **R), P("Bonus (so'm)", bold=True, **R)]]
        for i, ln in enumerate(rows, 1):
            body.append([P(i), P(ln["order_ref"]), P(ln["title"]), P(usd(ln["amount"]), **R), P(f"{ln['percent']} %", **R), P(money(ln["value"]), **R)])
        body.append(["", "", P("JAMI", bold=True), "", "", P(money(sec["total"]), bold=True, **R)])
        out.append(_grid(body, [10 * mm, 20 * mm, WIDTH - 122 * mm, 30 * mm, 22 * mm, 40 * mm], bold_last=True))
    elif key == "collect":
        body = [[P("№", bold=True), P("ID", bold=True), P("Topshirildi", bold=True), P("Pul yechildi", bold=True), P("Kun", bold=True, **R), P("Summa", bold=True, **R), P("Foiz", bold=True, **R), P("Bonus (so'm)", bold=True, **R)]]
        for i, ln in enumerate(rows, 1):
            amt = usd(ln["amount"]) if ln["currency"] == "USD" else money(ln["amount"])
            pct = "" if ln["percent"] is None else f"{ln['percent']} %"
            body.append([P(i), P(ln["order_ref"]), P(ddmm(ln["on_date"])), P(ddmm(ln["paid_on"])), P("" if ln["days"] is None else ln["days"], **R), P(amt, **R), P(pct, **R), P(money(ln["value"]), **R)])
        body.append(["", "", "", "", "", P("JAMI", bold=True), "", P(money(sec["total"]), bold=True, **R)])
        out.append(_grid(body, [9 * mm, 18 * mm, 22 * mm, 22 * mm, 12 * mm, WIDTH - 157 * mm, 20 * mm, 54 * mm], bold_last=True))
    elif key == "deduction":
        body = [[P("№", bold=True), P("Sana", bold=True), P("Nomi / izoh", bold=True), P("Summa", bold=True, **R), P("So'mda", bold=True, **R)]]
        for i, ln in enumerate(rows, 1):
            amt = usd(ln["amount"]) if ln["currency"] == "USD" else money(ln["amount"])
            body.append([P(i), P(ddmm(ln["on_date"])), P(ln["title"]), P(amt, **R), P(money(ln["value"]), **R)])
        body.append(["", "", P("JAMI", bold=True), "", P(money(sec["total"]), bold=True, **R)])
        out.append(_grid(body, [10 * mm, 22 * mm, WIDTH - 104 * mm, 32 * mm, 40 * mm], bold_last=True))
    return out


def render_pdf(v: dict) -> bytes:
    _register()
    buf = io.BytesIO()
    approved = v.get("status") == "approved"

    def stamp(c, doc):
        c.saveState()
        c.setFont("Mont", 7)
        c.setFillColor(colors.grey)
        c.drawString(12 * mm, 8 * mm, f"Oylik varaqasi №{v['number']}" + (f" · v{v['version']}" if v.get("version", 0) > 1 else ""))
        c.drawRightString(A4[0] - 12 * mm, 8 * mm, "ser-mebel.uz")
        if not approved:
            c.setFont("Mont-Bold", 60)
            c.setFillColor(colors.Color(0.85, 0.2, 0.2, alpha=0.12))
            c.translate(A4[0] / 2, A4[1] / 2)
            c.rotate(35)
            c.drawCentredString(0, 0, "QORALAMA")
        c.restoreState()

    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=10 * mm, bottomMargin=14 * mm,
        title=f"Oylik varaqasi №{v['number']} — {v['worker']}",
    )
    story: list = []
    head = Table([[P(f"{v['kind_label'].upper()} — OYLIK HISOBOT VARAG'I", bold=True, size=12, color=colors.white)]], colWidths=[WIDTH])
    head.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story.append(head)
    people = ", ".join(m["name"] for m in v.get("members", [])[1:])
    info = [
        [P("Xodim (F.I.Sh.)", bold=True), P(v["worker"]), P("Oy", bold=True), P(v["month_label"])],
        [P("Lavozim", bold=True), P(v.get("position")), P("Davr", bold=True), P(f"{ddmm(v['period_start'])} — {ddmm(v['period_end'])}")],
        [P("Soha / bo'lim", bold=True), P(v.get("section")), P("1 USD kursi", bold=True), P(money(v["usd_rate"]) + " so'm")],
    ]
    if people:
        info.append([P("Sheriklar", bold=True), P(people), P("Hisob sanasi", bold=True), P(ddmm(v.get("pay_date")))])
    story.append(_grid(info, [32 * mm, WIDTH / 2 - 32 * mm, 28 * mm, WIDTH / 2 - 28 * mm], head=False))

    fields = v.get("fields", [])
    if "fixed" in fields:
        story += [Spacer(1, 3 * mm), _grid([[P("Oklad" if v["kind"] == "ofis" else "Fiksa (oylik maosh), so'm", bold=True), P(money(v["fixed"]), bold=True, **R)]], [WIDTH - 45 * mm, 45 * mm], head=False)]
    for sec in v["sections"]:
        story += _section(sec, v["lines"])
    if "instagram" in fields:
        story += [Spacer(1, 3 * mm), _grid([[P("Instagram istoriyalar soni", bold=True), P(v["instagram_count"], **R), P(f"Bonus: {usd(v['totals']['instagram_usd'])}", **R)]], [WIDTH - 80 * mm, 30 * mm, 50 * mm], head=False)]
    if "late" in fields or "absent" in fields:
        body = [[P("Nomi", bold=True), P("Sanalar", bold=True), P("Kun", bold=True, **R), P("Bir kun (so'm)", bold=True, **R), P("Summa (so'm)", bold=True, **R)]]
        if "late" in fields:
            body.append([P("Kech qolgan (shtraf)"), P(v["late_dates"]), P(v["late_days"], **R), P(money(v["late_rate"]), **R), P(money(v["late_days"] * Decimal(v["late_rate"])), **R)])
        if "absent" in fields:
            body.append([P("Kelmagan kunlar"), P(v["absent_dates"]), P(v["absent_days"], **R), P(money(v["absent_rate"]), **R), P(money(v["absent_days"] * Decimal(v["absent_rate"])), **R)])
        story += [Spacer(1, 3 * mm), _title("Kech qolgan va kelmagan kunlar"), _grid(body, [40 * mm, WIDTH - 130 * mm, 15 * mm, 35 * mm, 40 * mm])]

    story += [Spacer(1, 3 * mm), _title("Olingan avanslar")]
    body = [[P("№", bold=True), P("Sana", bold=True), P("Kim oldi", bold=True), P("Kim berdi / izoh", bold=True), P("Asl summa", bold=True, **R), P("So'm", bold=True, **R)]]
    for i, a in enumerate(v["advances"], 1):
        orig = usd(a["orig_amount"]) if a["currency"] == "USD" else ""
        body.append([P(i), P(ddmm(a["date"])), P(a["worker"]), P(" · ".join(x for x in (a["given_by"], a["comment"]) if x)), P(orig, **R), P(money(a["amount"]), **R)])
    if not v["advances"]:
        body.append(["", "", P("Bu davrda avans berilmagan"), "", "", ""])
    body.append(["", "", P("JAMI AVANSLAR", bold=True), "", "", P(money(v["totals"]["advances_total"]), bold=True, **R)])
    story.append(_grid(body, [9 * mm, 20 * mm, 36 * mm, WIDTH - 133 * mm, 28 * mm, 40 * mm], bold_last=True))

    t = v["totals"]
    story += [Spacer(1, 3 * mm), _title("Yakuniy hisob-kitob")]
    body = []
    for x in t["earned"]:
        body.append([P(x["label"]), P(money(x["amount"]), **R)])
    body.append([P("JAMI HISOBLANGAN", bold=True), P(money(t["earned_total"]), bold=True, **R)])
    for x in t["minus"]:
        body.append([P(f"(−) {x['label']}"), P(money(x["amount"]), **R)])
    body.append([P("(−) Olingan avanslar"), P(money(t["advances_total"]), **R)])
    rest = Decimal(t["rest"])
    label = "OSTATOK (xodimga berilishi kerak)" if rest >= 0 else "QARZ (xodim ortiqcha olgan)"
    extra = f"  ({usd(t['rest_usd'])})" if t.get("rest_usd") else ""
    body.append([P(label, bold=True, size=10), P(money(t["rest"]) + " so'm" + extra, bold=True, size=10, **R)])
    story.append(_grid(body, [WIDTH - 60 * mm, 60 * mm], head=False, bold_last=True))
    if t.get("car_total") is not None and Decimal(t["car_total"]) > 0:
        story.append(P(f"Mashina puli alohida: {money(t['car_total'])} so'm (qoldiqqa kirmagan).", size=8))

    if v.get("members") and len(v["members"]) > 1:
        story += [Spacer(1, 3 * mm), _title("Ulushlar taqsimoti")]
        body = [[P("Kim", bold=True), P("Ulush", bold=True, **R), P("Hisoblangan", bold=True, **R), P("Avans oldi", bold=True, **R), P("Qoldiq", bold=True, **R)]]
        for m in v["members"]:
            body.append([P(m["name"]), P(f"{m['share']} %", **R), P(money(m["amount"]), **R), P(money(m["advances"]), **R), P(money(m["rest"]), bold=True, **R)])
        story.append(_grid(body, [WIDTH - 140 * mm, 20 * mm, 40 * mm, 40 * mm, 40 * mm]))

    if v.get("note"):
        story += [Spacer(1, 2 * mm), P("Izoh: " + v["note"], size=8)]
    story.append(Spacer(1, 8 * mm))
    signs = [[P(f"{v['worker']}: ____________"), P("Rahbar: ____________", **R)]]
    for m in v.get("members", [])[1:]:
        signs.append([P(f"{m['name']}: ____________"), ""])
    sign_t = Table(signs, colWidths=[WIDTH / 2, WIDTH / 2])
    story.append(sign_t)
    if approved and v.get("approved_by"):
        story += [Spacer(1, 2 * mm), P(f"Tasdiqladi: {v['approved_by']} · {ddmm(v.get('approved_at'))}", size=7.5, color=colors.grey)]
    doc.build(story, onFirstPage=stamp, onLaterPages=stamp)
    return buf.getvalue()
