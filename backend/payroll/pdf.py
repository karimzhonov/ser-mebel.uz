"""The printable salary sheet, drawn from payroll.services.sheet_view() — the same data
the page shows, so the paper and the screen never disagree. The layout follows the
office Excel templates: header, the kind's sections, advances, the final sum and
signatures. A sheet that is not approved yet is stamped «QORALAMA».

Two paper sizes: A4 (default) and A5 (a short ODDIY sheet fits on half a page).
Everything is laid out on an A4-wide grid and scaled to the chosen paper, so both
sizes share one layout."""

from __future__ import annotations

import io
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONTS = Path(__file__).resolve().parents[1] / "accounting" / "fonts"
NAVY = colors.HexColor("#1F3864")
SOFT = colors.HexColor("#EEF2F8")
LINE = colors.HexColor("#C9D3E3")
PAPERS = {"a4": A4, "a5": A5}
BASE_W = 186 * mm  # the grid every width below is written for (A4 minus margins)

_fonts = False


def _register() -> None:
    global _fonts
    if not _fonts:
        pdfmetrics.registerFont(TTFont("Mont", str(FONTS / "Montserrat-Regular.ttf")))
        pdfmetrics.registerFont(TTFont("Mont-Bold", str(FONTS / "Montserrat-Bold.ttf")))
        _fonts = True


def _esc(s) -> str:
    return str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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


def short(s: str, n: int) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


R = {"align": TA_RIGHT}


@dataclass
class Layout:
    """Paper + scale: `w(x)` turns an A4-grid width into this paper's width."""

    paper: tuple
    margin: float

    @property
    def width(self) -> float:
        return self.paper[0] - 2 * self.margin

    @property
    def k(self) -> float:
        return self.width / BASE_W

    def w(self, x: float) -> float:
        return x * self.k

    def ws(self, *xs: float) -> list[float]:
        """Column widths; a None takes what is left of the line."""
        fixed = sum(self.w(x) for x in xs if x is not None)
        rest = max(self.width - fixed, 10 * mm * self.k)
        return [rest if x is None else self.w(x) for x in xs]

    def st(self, size=7.5, bold=False, align=0, color=colors.black) -> ParagraphStyle:
        size = size * max(self.k, 0.78)  # A5 keeps the type readable
        return ParagraphStyle(
            "x",
            fontName="Mont-Bold" if bold else "Mont",
            fontSize=size,
            leading=size * 1.22,
            alignment=align,
            textColor=color,
        )

    def P(self, text, **kw) -> Paragraph:
        return Paragraph(_esc(text), self.st(**kw))

    def gap(self, x=2.2) -> Spacer:
        return Spacer(1, x * mm * self.k)

    def grid(self, rows, widths, head=True, bold_last=False) -> Table:
        t = Table(rows, colWidths=widths, repeatRows=1 if head else 0)
        pad = 1.6 * self.k
        style = [
            ("GRID", (0, 0), (-1, -1), 0.35, LINE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), pad),
            ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
            ("LEFTPADDING", (0, 0), (-1, -1), 3 * self.k),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3 * self.k),
        ]
        if head:
            style.append(("BACKGROUND", (0, 0), (-1, 0), SOFT))
        if bold_last:
            style.append(("BACKGROUND", (0, -1), (-1, -1), SOFT))
        t.setStyle(TableStyle(style))
        return t

    def title(self, text: str) -> Table:
        t = Table([[self.P(text, bold=True, color=colors.white, size=8)]], colWidths=[self.width])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                    ("TOPPADDING", (0, 0), (-1, -1), 2 * self.k),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * self.k),
                ]
            )
        )
        return t


def _section(L: Layout, sec: dict, lines: list[dict]) -> list:
    P = L.P
    key = sec["key"]
    rows = [ln for ln in lines if ln["section"] == key]
    out = [L.gap(), L.title(sec["title"])]
    if key in ("job", "car"):
        body = [[P("№", bold=True), P("ID", bold=True), P("Mijoz / ish nomi", bold=True), P("Summa (so'm)", bold=True, **R)]]
        for i, ln in enumerate(rows, 1):
            body.append([P(i), P(ln["order_ref"]), P(short(ln["title"], 60)), P(money(ln["value"]), **R)])
        body.append(["", "", P("JAMI", bold=True), P(money(sec["total"]), bold=True, **R)])
        out.append(L.grid(body, L.ws(9 * mm, 20 * mm, None, 36 * mm), bold_last=True))
    elif key in ("taken", "delivered"):
        body = [[P("№", bold=True), P("ID", bold=True), P("Mijoz / ish nomi", bold=True), P("Zakaz ($)", bold=True, **R), P("Foiz", bold=True, **R), P("Bonus (so'm)", bold=True, **R)]]
        for i, ln in enumerate(rows, 1):
            body.append([P(i), P(ln["order_ref"]), P(short(ln["title"], 50)), P(usd(ln["amount"]), **R), P(f"{ln['percent']} %", **R), P(money(ln["value"]), **R)])
        body.append(["", "", P("JAMI", bold=True), "", "", P(money(sec["total"]), bold=True, **R)])
        out.append(L.grid(body, L.ws(9 * mm, 18 * mm, None, 28 * mm, 18 * mm, 34 * mm), bold_last=True))
    elif key == "collect":
        body = [[P("№", bold=True), P("ID", bold=True), P("Topshirildi", bold=True), P("Pul yechildi", bold=True), P("Kun", bold=True, **R), P("Summa", bold=True, **R), P("Foiz", bold=True, **R), P("Bonus (so'm)", bold=True, **R)]]
        for i, ln in enumerate(rows, 1):
            amt = usd(ln["amount"]) if ln["currency"] == "USD" else money(ln["amount"])
            pct = "" if ln["percent"] is None else f"{ln['percent']} %"
            body.append([P(i), P(ln["order_ref"]), P(ddmm(ln["on_date"])), P(ddmm(ln["paid_on"])), P("" if ln["days"] is None else ln["days"], **R), P(amt, **R), P(pct, **R), P(money(ln["value"]), **R)])
        body.append(["", "", "", "", "", P("JAMI", bold=True), "", P(money(sec["total"]), bold=True, **R)])
        out.append(L.grid(body, L.ws(9 * mm, 17 * mm, 21 * mm, 21 * mm, 11 * mm, None, 16 * mm, 34 * mm), bold_last=True))
    elif key == "deduction":
        body = [[P("№", bold=True), P("Sana", bold=True), P("Nomi / izoh", bold=True), P("Summa", bold=True, **R), P("So'mda", bold=True, **R)]]
        for i, ln in enumerate(rows, 1):
            amt = usd(ln["amount"]) if ln["currency"] == "USD" else money(ln["amount"])
            body.append([P(i), P(ddmm(ln["on_date"])), P(short(ln["title"], 60)), P(amt, **R), P(money(ln["value"]), **R)])
        body.append(["", "", P("JAMI", bold=True), "", P(money(sec["total"]), bold=True, **R)])
        out.append(L.grid(body, L.ws(9 * mm, 21 * mm, None, 28 * mm, 34 * mm), bold_last=True))
    return out


def _advances(L: Layout, v: dict) -> list:
    """One short line per advance: date, (who, when partners share the sheet), who
    gave it + comment cut to one line, so'm (the $ original in brackets)."""
    P = L.P
    many = len({a["worker"] for a in v["advances"]}) > 1 or len(v.get("members") or []) > 1
    text_len = 70 if L.k > 0.9 else 46
    head = [P("№", bold=True), P("Sana", bold=True)]
    if many:
        head.append(P("Kim oldi", bold=True))
    head += [P("Kim berdi · izoh", bold=True), P("So'm", bold=True, **R)]
    body = [head]
    for i, a in enumerate(v["advances"], 1):
        giver = short(a["given_by"], 24)
        note = " · ".join(x for x in (giver, a["comment"]) if x)
        amount = money(a["amount"]) + (f" ({usd(a['orig_amount'])})" if a["currency"] == "USD" else "")
        row = [P(i, size=7), P(ddmm(a["date"]), size=7)]
        if many:
            row.append(P(short(a["worker"], 18), size=7))
        row += [P(short(note, text_len), size=7), P(amount, size=7, **R)]
        body.append(row)
    blank = [""] * (len(head) - 1)
    if not v["advances"]:
        body.append(blank[:1] + [P("Bu davrda avans berilmagan", size=7)] + blank[2:] + [""])
    body.append(blank[:-1] + [P("JAMI AVANSLAR", bold=True, **R), P(money(v["totals"]["advances_total"]), bold=True, **R)])
    widths = L.ws(8 * mm, 19 * mm, *((28 * mm,) if many else ()), None, 34 * mm)
    return [L.gap(), L.title(f"Olingan avanslar ({len(v['advances'])} ta)"), L.grid(body, widths, bold_last=True)]


def render_pdf(v: dict, size: str = "a4") -> bytes:
    _register()
    L = Layout(PAPERS.get(size, A4), (12 if size != "a5" else 8) * mm)
    P = L.P
    W = L.width
    buf = io.BytesIO()
    approved = v.get("status") == "approved"
    page_w, page_h = L.paper

    def stamp(c, doc):
        c.saveState()
        c.setFont("Mont", 6.5 * max(L.k, 0.8))
        c.setFillColor(colors.grey)
        c.drawString(L.margin, 6 * mm, f"Oylik varaqasi №{v['number']}" + (f" · v{v['version']}" if v.get("version", 0) > 1 else ""))
        c.drawRightString(page_w - L.margin, 6 * mm, "ser-mebel.uz")
        if not approved:
            c.setFont("Mont-Bold", 60 * L.k)
            c.setFillColor(colors.Color(0.85, 0.2, 0.2, alpha=0.12))
            c.translate(page_w / 2, page_h / 2)
            c.rotate(35)
            c.drawCentredString(0, 0, "QORALAMA")
        c.restoreState()

    doc = SimpleDocTemplate(
        buf,
        pagesize=L.paper,
        leftMargin=L.margin,
        rightMargin=L.margin,
        topMargin=L.margin * 0.75,
        bottomMargin=11 * mm,
        title=f"Oylik varaqasi №{v['number']} — {v['worker']}",
    )
    story: list = []
    head = Table([[P(f"{v['kind_label'].upper()} — OYLIK HISOBOT VARAG'I", bold=True, size=10.5, color=colors.white)]], colWidths=[W])
    head.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("TOPPADDING", (0, 0), (-1, -1), 4 * L.k), ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * L.k)]))
    story.append(head)
    people = ", ".join(m["name"] for m in v.get("members", [])[1:])
    info = [
        [P("Xodim", bold=True), P(v["worker"]), P("Oy", bold=True), P(v["month_label"])],
        [P("Lavozim", bold=True), P(v.get("position")), P("Davr", bold=True), P(f"{ddmm(v['period_start'])} — {ddmm(v['period_end'])}")],
        [P("Soha / bo'lim", bold=True), P(v.get("section")), P("1 USD kursi", bold=True), P(money(v["usd_rate"]) + " so'm")],
    ]
    if people:
        info.append([P("Sheriklar", bold=True), P(people), P("Hisob sanasi", bold=True), P(ddmm(v.get("pay_date")))])
    story.append(L.grid(info, [L.w(28 * mm), W / 2 - L.w(28 * mm), L.w(26 * mm), W / 2 - L.w(26 * mm)], head=False))

    fields = v.get("fields", [])
    if "fixed" in fields:
        story += [L.gap(), L.grid([[P("Oklad" if v["kind"] == "ofis" else "Fiksa (oylik maosh), so'm", bold=True), P(money(v["fixed"]), bold=True, **R)]], L.ws(None, 40 * mm), head=False)]
    for sec in v["sections"]:
        story += _section(L, sec, v["lines"])
    if "instagram" in fields:
        story += [L.gap(), L.grid([[P("Instagram istoriyalar soni", bold=True), P(v["instagram_count"], **R), P(f"Bonus: {usd(v['totals']['instagram_usd'])}", **R)]], L.ws(None, 26 * mm, 44 * mm), head=False)]
    if "late" in fields or "absent" in fields:
        body = [[P("Nomi", bold=True), P("Sanalar", bold=True), P("Kun", bold=True, **R), P("Bir kun", bold=True, **R), P("Summa (so'm)", bold=True, **R)]]
        if "late" in fields:
            body.append([P("Kech qolgan (shtraf)"), P(v["late_dates"]), P(v["late_days"], **R), P(money(v["late_rate"]), **R), P(money(v["late_days"] * Decimal(v["late_rate"])), **R)])
        if "absent" in fields:
            body.append([P("Kelmagan kunlar"), P(v["absent_dates"]), P(v["absent_days"], **R), P(money(v["absent_rate"]), **R), P(money(v["absent_days"] * Decimal(v["absent_rate"])), **R)])
        story += [L.gap(), L.title("Kech qolgan va kelmagan kunlar"), L.grid(body, L.ws(38 * mm, None, 13 * mm, 30 * mm, 34 * mm))]

    story += _advances(L, v)

    t = v["totals"]
    story += [L.gap(), L.title("Yakuniy hisob-kitob")]
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
    body.append([P(label, bold=True, size=9), P(money(t["rest"]) + " so'm" + extra, bold=True, size=9, **R)])
    story.append(L.grid(body, L.ws(None, 62 * mm), head=False, bold_last=True))
    if t.get("car_total") is not None and Decimal(t["car_total"]) > 0:
        story.append(P(f"Mashina puli alohida: {money(t['car_total'])} so'm (qoldiqqa kirmagan).", size=7))

    if v.get("members") and len(v["members"]) > 1:
        story += [L.gap(), L.title("Ulushlar taqsimoti")]
        body = [[P("Kim", bold=True), P("Ulush", bold=True, **R), P("Hisoblangan", bold=True, **R), P("Avans oldi", bold=True, **R), P("Qoldiq", bold=True, **R)]]
        for m in v["members"]:
            body.append([P(m["name"]), P(f"{m['share']} %", **R), P(money(m["amount"]), **R), P(money(m["advances"]), **R), P(money(m["rest"]), bold=True, **R)])
        story.append(L.grid(body, L.ws(None, 18 * mm, 36 * mm, 36 * mm, 36 * mm)))

    if v.get("note"):
        story += [L.gap(1.5), P("Izoh: " + v["note"], size=7)]
    story.append(L.gap(6))
    signs = [[P(f"{v['worker']}: ____________"), P("Rahbar: ____________", **R)]]
    for m in v.get("members", [])[1:]:
        signs.append([P(f"{m['name']}: ____________"), ""])
    story.append(Table(signs, colWidths=[W / 2, W / 2]))
    if approved and v.get("approved_by"):
        story += [L.gap(1.5), P(f"Tasdiqladi: {v['approved_by']} · {ddmm(v.get('approved_at'))}", size=6.5, color=colors.grey)]
    doc.build(story, onFirstPage=stamp, onLaterPages=stamp)
    return buf.getvalue()
