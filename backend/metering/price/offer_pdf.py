"""The commercial offer («Тижорат таклифи») as a PDF — GET /api/v1/prices/{id}/pdf/.

Layout follows the owner's template (Canva, 1440×810, Montserrat): cover → about us →
for every room a photo page (renders / drawings) and a price page → total → delivery →
terms → thanks. The decorated pages reuse the template's own backgrounds (offer/*.png);
everything with data is drawn here. Content comes from services.offer_data(), the same
structure the page and the Excel show.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image as PILImage
from PIL import ImageOps
from reportlab.lib.colors import HexColor, white
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .services import offer_data

log = logging.getLogger(__name__)

W, H = 1440, 810
HERE = Path(__file__).resolve().parent / "offer"
FONTS = Path(__file__).resolve().parents[2] / "accounting" / "fonts"

DARK = HexColor("#0F2E2E")  # «ТИЖОРАТ», body text
FOREST = HexColor("#344E41")  # room titles
GREEN = HexColor("#12A150")  # totals
GREY_BG = HexColor("#D9D9D9")  # room pages
LINE = HexColor("#C9CFCC")
MUTED = HexColor("#5B6B66")
HEAD = HexColor("#1F3B33")

PHONE = "+99899 000 60 09"
TELEGRAM = "T.ME/SERMEBEL"
INSTAGRAM = "SERMEBEL_UZ"
ADDRESS = "МАЛАЯ КОЛЬЦЕВАЯ ДОРОГА 2/А"
SITE = "myurls.co/sermebel"

ABOUT = [
    "SERMEBEL — бу шунчаки мебель эмас. Бу услуб, шинамлик ва сифат уйғунлиги бўлиб, "
    "уйингиз ҳақида ғамхўрлик билан яратилган. 2014 йилдан бери мижозларимизга интерьер "
    "орзуларини рўёбга чиқаришда ёрдам бериб келмоқдамиз — шинам ётоқхоналардан тортиб "
    "замонавий ошхоналар ва қулай меҳмонхоналаргача.",
    "Ассортиментимизда — сифатли материаллардан тайёрланган мебель, замонавий дизайн ва "
    "ҳар қандай дид ва бюджетга мос индивидуал ечимлар.",
    "Бизнинг миссиямиз — биринчи қарашдаёқ севги уйғотадиган ва йиллар давомида хизмат "
    "қиладиган мебель яратиш. Биз ҳалоллик, қулайлик ва ишончни қадрлаймиз, шунинг учун "
    "ҳар бир буюртма биз учун шахсий тарих бўлиб, унга юракдан ёндашамиз.",
]
DELIVERY = [
    "Биз сизнинг қулайлигингиз ҳақида ҳар бир босқичда ғамхўрлик қиламиз — мебель "
    "танлашдан бошлаб, уни уйингизга етказиб беришгача.",
    "**Етказиб бериш:** шаҳар ва вилоят бўйлаб тезкор ва эҳтиёткорлик билан етказиб "
    "берамиз. Барча маҳсулотлар ишончли тарзда ўралади, шунда улар идеал ҳолатда етиб боради.",
    "**Ўрнатиш:** профессионал монтажчилар жамоамиз мебелни жойида эҳтиёткорлик билан "
    "йиғиб, ўрнатади. Ортиқча шовқин, чанг ва бош оғриқсиз — етказилган куннинг ўзида "
    "фойдаланишга тайёр бўлади.",
    "**Биз билан — осон:**",
    "— қулай етказиб бериш вақти",
    "— масъулиятли мутахассислар",
    "— ўрнатишга кафолат",
    "**SERMEBEL** — қулайликни тўғридан-тўғри уйингизга олиб келамиз.",
]
TERMS = [
    "Биз сиз учун харид жараёнини иложи борича қулай қилишга интиламиз.",
    "**Ишлаб чиқариш муддати** мебель турига ва буюртманинг индивидуал хусусиятларига "
    "қараб белгиланади:",
    "— стандарт моделлар — 30 дан 40 иш кунигача",
    "— индивидуал лойиҳалар — 45 дан 60 иш кунигача",
    "Аниқ муддатлар буюртма тасдиқлангандан сўнг айтилади. Биз ҳар доим белгиланган "
    "муддатларга риоя қиламиз, барча босқичларда юқори сифатни сақлаган ҳолда.",
    "**Тўлов шартлари:**",
    "— олдиндан тўлов — умумий суммадан 70% дан бошлаб (буюм турига қараб)",
    "— якуний ҳисоб-китоб — мебель етказиб берилганда ва ўрнатилганда",
    "Ўзингизни ишончли ҳис қилишингиз учун барча керакли ҳужжатлар ва шартномани тақдим этамиз.",
    "**Ser Mebel** — қулайлик ишончдан бошланади.",
]

_fonts_ready = False


def _register_fonts():
    global _fonts_ready
    if _fonts_ready:
        return
    pdfmetrics.registerFont(TTFont("Mont", str(FONTS / "Montserrat-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Mont-Bold", str(FONTS / "Montserrat-Bold.ttf")))
    _fonts_ready = True


def money(v) -> str:
    """30142 → «30 142 $» (the template's way)."""
    v = round(float(v or 0), 2)
    whole = f"{int(v):,}".replace(",", " ")
    frac = f"{v:.2f}".split(".")[1]
    return f"{whole}{'' if frac == '00' else ',' + frac} $"


class Offer:
    def __init__(self, price):
        _register_fonts()
        self.data = offer_data(price)
        self.buf = io.BytesIO()
        self.c = canvas.Canvas(self.buf, pagesize=(W, H))
        self.c.setTitle(f"Тижорат таклифи — {self.data['client']}")
        self.c.setAuthor("SERMEBEL")

    # ------------------------------------------------------------------ helpers
    def y(self, top: float) -> float:
        """Template coordinates are from the top; reportlab's from the bottom."""
        return H - top

    def bg(self, name: str):
        self.c.drawImage(ImageReader(str(HERE / name)), 0, 0, W, H)

    def fill_page(self, color):
        self.c.setFillColor(color)
        self.c.rect(0, 0, W, H, stroke=0, fill=1)

    def text(self, x, top, s, *, size, bold=False, color=DARK, align="l", space=0.0, max_w=None):
        font = "Mont-Bold" if bold else "Mont"
        s = str(s)
        while max_w and size > 8 and self.width(s, size, bold, space) > max_w:
            size -= 1
        w = self.width(s, size, bold, space)
        if align == "c":
            x -= w / 2
        elif align == "r":
            x -= w
        self.c.setFillColor(color)
        self.c.setFont(font, size)
        self.c.drawString(x, self.y(top), s, charSpace=space)
        return w

    @staticmethod
    def width(s, size, bold=False, space=0.0):
        font = "Mont-Bold" if bold else "Mont"
        return pdfmetrics.stringWidth(str(s), font, size) + space * max(len(str(s)) - 1, 0)

    def paragraphs(self, x, top, width, paras, *, size=16, leading=None, gap=8, color=DARK):
        """Plain paragraphs; «**bold:**» at the start of one is drawn bold."""
        leading = leading or size * 1.35
        cy = top
        for p in paras:
            bold_head = ""
            if p.startswith("**"):
                end = p.find("**", 2)
                bold_head, p = p[2:end], p[end + 2 :].lstrip()
            first = True
            if bold_head:
                hw = self.text(x, cy, bold_head, size=size, bold=True, color=color)
                rest_w = width - hw - size * 0.3
                if p:
                    head_lines = simpleSplit(p, "Mont", size, rest_w)
                    self.text(x + hw + size * 0.3, cy, head_lines[0], size=size, color=color)
                    p = p[len(head_lines[0]) :].lstrip()
                cy += leading
                first = False
            for line in simpleSplit(p, "Mont", size, width) if p else []:
                self.text(x, cy, line, size=size, color=color)
                cy += leading
                first = False
            if first:
                cy += leading
            cy += gap
        return cy

    def url_box(self, x, top, w, h=50):
        c = self.c
        c.setStrokeColor(DARK)
        c.setLineWidth(1.4)
        c.setFillColor(white)
        c.roundRect(x, self.y(top + h), w, h, 12, stroke=1, fill=1)
        # magnifier
        cx, cy = x + 30, self.y(top + h / 2) + 3
        c.setLineWidth(3)
        c.circle(cx, cy, 8, stroke=1, fill=0)
        c.line(cx + 6, cy - 6, cx + 13, cy - 13)
        self.text(x + 62, top + h / 2 + 6, f"http://{SITE}", size=17, bold=True)

    # ------------------------------------------------------------------ pages
    def cover(self):
        d = self.data
        self.bg("bg_cover.png")
        self.text(1385, 60, "СМЕТЧИК", size=16, align="r")
        self.text(1385, 90, (d["estimator"] or "SERMEBEL").upper(), size=17, bold=True, align="r")
        self.text(1385, 119, d["date"].strftime("%d.%m.%Y"), size=16, align="r")
        a, b = "ТИЖОРАТ ", "ТАКЛИФИ"
        wa, wb = self.width(a, 66, True), self.width(b, 66)
        x0 = W / 2 - (wa + wb) / 2
        self.text(x0, 262, a, size=66, bold=True)
        self.text(x0 + wa, 262, b, size=66)
        self.text(W / 2, 305, "ХУРМАТЛИ", size=31, align="c", space=7)
        if d["client"]:
            self.text(W / 2, 352, d["client"].upper(), size=31, align="c", space=7, max_w=900)

    def about(self):
        self.bg("bg_about.png")
        w = self.text(95, 172, "БИЗ ", size=60, bold=True, color=FOREST)
        self.text(95 + w, 172, "ҲАҚИМИЗДА", size=60)
        self.paragraphs(82, 222, 580, ABOUT, size=16.5, gap=10)
        self.url_box(98, 700, 495)

    def room_photos(self, room):
        imgs = [r for r in (self._load(f) for f in room["images"]) if r]
        for start in range(0, len(imgs), 6):
            chunk = imgs[start : start + 6]
            self.fill_page(GREY_BG)
            title = room["name"].upper() + (" (давоми)" if start else "")
            self.text(W / 2, 92, title, size=54, bold=True, color=FOREST, align="c", max_w=1200)
            n = len(chunk)
            split = {1: [1], 2: [2], 3: [3], 4: [2, 2], 5: [3, 2]}.get(n, [3, 3])
            rows, i = [], 0
            for k in split:
                rows.append(chunk[i : i + k])
                i += k
            # every row: same height for all its pictures, as wide as the page allows
            aw, ah, gap, top = W - 120, H - 140 - 45, 24, 140
            row_ah = (ah - gap * (len(rows) - 1)) / len(rows)
            heights = [
                min(row_ah, (aw - gap * (len(r) - 1)) / sum(iw / ih for _, iw, ih in r))
                for r in rows
            ]
            cy = top + (ah - sum(heights) - gap * (len(rows) - 1)) / 2
            c = self.c
            for r, h in zip(rows, heights):
                widths = [h * iw / ih for _, iw, ih in r]
                cx = (W - sum(widths) - gap * (len(r) - 1)) / 2
                for (reader, _, _), w in zip(r, widths):
                    c.saveState()
                    p = c.beginPath()
                    p.roundRect(cx, self.y(cy + h), w, h, 14)
                    c.clipPath(p, stroke=0, fill=0)
                    c.drawImage(reader, cx, self.y(cy + h), w, h)
                    c.restoreState()
                    cx += w + gap
                cy += h + gap
            self.c.showPage()

    def _load(self, f):
        """A filer file → (ImageReader, w, h), downscaled so the PDF stays small."""
        try:
            with f.file.open("rb") as fh:
                im = PILImage.open(fh)
                im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((1800, 1800))
            out = io.BytesIO()
            im.save(out, "JPEG", quality=85)
            out.seek(0)
            return ImageReader(out), im.width, im.height
        except Exception:
            log.warning("offer pdf: image %s could not be read", getattr(f, "pk", "?"))
            return None

    # The price table: МЕБЕЛЬ | МАТЕРИАЛ | СТОИМОСТЬ, one block per furniture item,
    # every «label: material» on its own aligned row.
    TX, TW = 80, 1280
    C1, C2 = 400, 1040  # column borders (x from TX)
    ROW_H, PAD = 27, 14

    def room_prices(self, room):
        blocks = [self._block(it) for it in room["items"]]
        page_blocks, cur, used = [], [], 0
        room_h = H - 205 - 60 - 64  # table body space: header 56 + total row 64 + margins
        for b in blocks:
            if cur and used + b[0] > room_h:
                page_blocks.append(cur)
                cur, used = [], 0
            cur.append(b)
            used += b[0]
        page_blocks.append(cur)
        for pi, chunk in enumerate(page_blocks):
            last = pi == len(page_blocks) - 1
            self._price_page(room, chunk, last, cont=pi > 0)

    def _block(self, it):
        name = it["name"].upper()
        name_lines = simpleSplit(name, "Mont-Bold", 17, self.C1 - 30)
        rows = []
        for p in it["params"] + ([{"label": "Допол.", "value": it["note"]}] if it["note"] else []):
            label_lines = simpleSplit(f"{p['label'].upper()}:", "Mont", 14, self.C1 - 30)
            value_lines = simpleSplit(str(p["value"]).upper(), "Mont", 16, self.C2 - self.C1 - 40)
            rows.append((label_lines, value_lines))
        h = self.PAD * 2 + len(name_lines) * 22
        if it["count_text"]:
            h += 20
        for lab, val in rows:
            h += max(len(lab), len(val)) * self.ROW_H * 0.8 + 6
        return (max(h, 70), it, name_lines, rows)

    def _price_page(self, room, blocks, last, cont):
        c = self.c
        self.fill_page(GREY_BG)
        w = self.text(115, 160, room["name"].upper(), size=50, bold=True, color=FOREST, max_w=760)
        self.text(115 + w + 30, 160, "ЦЕНА" + (" (давоми)" if cont else ""), size=50)
        tx, tw = self.TX, self.TW
        top = 195
        body_h = sum(b[0] for b in blocks) + (64 if last else 0)
        # card
        c.setFillColor(white)
        c.setStrokeColor(HexColor("#1B1B1B"))
        c.setLineWidth(1.5)
        c.roundRect(tx, self.y(top + 56 + body_h), tw, 56 + body_h, 10, stroke=1, fill=1)
        # header
        c.saveState()
        p = c.beginPath()
        p.roundRect(tx, self.y(top + 56 + body_h), tw, 56 + body_h, 10)
        c.clipPath(p, stroke=0, fill=0)
        c.setFillColor(HEAD)
        c.rect(tx, self.y(top + 56), tw, 56, stroke=0, fill=1)
        c.restoreState()
        for label, x0, x1 in (
            ("МЕБЕЛЬ", 0, self.C1),
            ("МАТЕРИАЛ", self.C1, self.C2),
            ("СТОИМОСТЬ", self.C2, tw),
        ):
            self.text(
                tx + (x0 + x1) / 2, top + 35, label, size=17, color=white, align="c", space=1.5
            )
        # column lines
        c.setStrokeColor(LINE)
        c.setLineWidth(1)
        for x in (self.C1, self.C2):
            c.line(tx + x, self.y(top + 56), tx + x, self.y(top + 56 + body_h))
        cy = top + 56
        for i, (h, it, name_lines, rows) in enumerate(blocks):
            if i:
                c.setStrokeColor(LINE)
                c.line(tx, self.y(cy), tx + tw, self.y(cy))
            y = cy + self.PAD + 17
            for ln in name_lines:
                self.text(tx + self.C1 / 2, y, ln, size=17, bold=True, color=DARK, align="c")
                y += 22
            if it["count_text"]:
                self.text(
                    tx + self.C1 / 2,
                    y - 2,
                    f"({it['count_text']})",
                    size=14,
                    color=MUTED,
                    align="c",
                )
                y += 20
            y += 4
            for lab, val in rows:
                ly = y
                for ln in lab:
                    self.text(tx + self.C1 / 2, ly, ln, size=14, color=MUTED, align="c")
                    ly += self.ROW_H * 0.8
                vy = y
                for ln in val:
                    self.text(tx + (self.C1 + self.C2) / 2, vy, ln, size=16, color=DARK, align="c")
                    vy += self.ROW_H * 0.8
                y = max(ly, vy) + 6
            self.text(
                tx + (self.C2 + tw) / 2,
                cy + h / 2 + 8,
                money(it["amount"]),
                size=22,
                bold=True,
                align="c",
            )
            cy += h
        if last:
            c.setFillColor(HexColor("#EEF7F1"))
            c.saveState()
            p = c.beginPath()
            p.roundRect(tx, self.y(top + 56 + body_h), tw, 56 + body_h, 10)
            c.clipPath(p, stroke=0, fill=0)
            c.rect(tx, self.y(cy + 64), tw, 64, stroke=0, fill=1)
            c.restoreState()
            c.setStrokeColor(HexColor("#1B1B1B"))
            c.setLineWidth(1.5)
            c.line(tx, self.y(cy), tx + tw, self.y(cy))
            self.text(
                tx + self.C2 - 30, cy + 41, "ИТОГО:", size=22, bold=True, color=GREEN, align="r"
            )
            self.text(
                tx + (self.C2 + tw) / 2,
                cy + 42,
                money(room["total"]),
                size=26,
                bold=True,
                color=GREEN,
                align="c",
            )
        c.showPage()

    def total(self):
        d = self.data
        self.bg("bg_total.png")
        top = 175
        self.text(W / 2, top, "ОБЩИЙ ИТОГ", size=56, bold=True, color=FOREST, align="c")
        if d["variant"]:
            top += 70
            self.text(
                W / 2,
                top,
                d["variant"].upper(),
                size=48,
                bold=True,
                color=FOREST,
                align="c",
                max_w=1100,
            )
        rooms = [r for r in d["rooms"] if r["items"]]
        size = 20 if len(rooms) <= 10 else 15
        lead = size * 1.75
        x0, x1 = 440, 1000
        cy = top + 60
        for r in rooms:
            self.text(x0, cy, r["name"], size=size, color=DARK, max_w=380)
            self.text(x1, cy, money(r["total"]), size=size, bold=True, align="r")
            self.c.setStrokeColor(LINE)
            self.c.setDash(2, 4)
            self.c.line(x0, self.y(cy + 8), x1, self.y(cy + 8))
            self.c.setDash()
            cy += lead
        cy += 30
        self.c.setFillColor(FOREST)
        self.c.roundRect(x0 - 20, self.y(cy + 40), x1 - x0 + 40, 64, 14, stroke=0, fill=1)
        self.text(
            W / 2,
            cy + 13,
            f"ИТОГ — {money(d['total'])}",
            size=34,
            bold=True,
            color=white,
            align="c",
        )

    def delivery(self):
        self.bg("bg_delivery.png")
        self.text(730, 140, "ЕТКАЗИБ БЕРИШ ВА", size=56, bold=True, color=FOREST, max_w=680)
        self.text(730, 222, "ЎРНАТИШ", size=56, bold=True, color=DARK)
        self.paragraphs(758, 285, 600, DELIVERY, size=15, gap=6)
        self.text(800, 720, f"http://{SITE}", size=17, bold=True)

    def terms(self):
        self.bg("bg_terms.png")
        self.text(98, 170, "ТАЙЁРЛАШ", size=62, bold=True, color=FOREST)
        self.text(98, 236, "МУДДАТИ", size=62, bold=True, color=DARK)
        self.paragraphs(98, 278, 590, TERMS, size=15, gap=7)

    def thanks(self):
        self.bg("bg_thanks.png")
        c = self.c
        c.setFillColor(white)  # hide the contacts baked into the background (old phone)
        c.rect(140, self.y(740), 420, 175, stroke=0, fill=1)
        self.text(90, 312, "СПАСИБО,", size=72, bold=True)
        for i, line in enumerate(("ЧТО ВЫБИРАЕТЕ", "КАЧЕСТВО И СТИЛЬ", "ВМЕСТЕ С НАМИ")):
            self.text(90, 382 + i * 57, line, size=40)
        for top, s in ((581, TELEGRAM), (622, INSTAGRAM), (664, PHONE), (707, ADDRESS)):
            self.text(150, top, s, size=14)
        self.text(167, 777, f"http://{SITE}", size=18, bold=True)

    def build(self) -> bytes:
        for page in (self.cover, self.about):
            page()
            self.c.showPage()
        for room in self.data["rooms"]:
            if room["images"]:
                self.room_photos(room)
            if room["items"]:
                self.room_prices(room)
        for page in (self.total, self.delivery, self.terms, self.thanks):
            page()
            self.c.showPage()
        self.c.save()
        return self.buf.getvalue()


def build_offer_pdf(price) -> bytes:
    return Offer(price).build()
