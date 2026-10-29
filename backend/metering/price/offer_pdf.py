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

from .services import client_measure_text as measure_text
from .services import offer_data, offer_lines

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
CARD_LINE = HexColor("#1B1B1B")

# One type scale for the whole offer (Montserrat Regular / Bold only)
T_HERO = 66  # cover title
T_PAGE = 56  # headings of the text pages
T_ROOM = 46  # room page titles
T_ITEM = 18  # furniture name
T_BODY = 16  # running text
T_VALUE = 15  # materials
T_LABEL = 13  # «ФАСАД МАТЕРИАЛ:» labels, captions
T_PRICE = 22  # a furniture price
T_TOTAL = 26  # a room total
ROOM_X, ROOM_TOP = 80, 112  # where every room page starts

PHONE = "+99899 000 60 09"
TELEGRAM = "T.ME/SERMEBEL"
INSTAGRAM = "SERMEBEL_UZ"
ADDRESS = "КИЧИК ҲАЛҚА ЙЎЛИ, 2/А"
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
    # body text of the text pages: a touch heavier than Regular reads better on grey
    pdfmetrics.registerFont(TTFont("Mont-Medium", str(HERE / "fonts" / "Montserrat-Medium.ttf")))
    pdfmetrics.registerFont(TTFont("Mont-Semi", str(HERE / "fonts" / "Montserrat-SemiBold.ttf")))
    _fonts_ready = True


def money(v) -> str:
    """30142 → «30 142 $» (the template's way)."""
    v = round(float(v or 0), 2)
    whole = f"{int(v):,}".replace(",", " ")
    frac = f"{v:.2f}".split(".")[1]
    return f"{whole}{'' if frac == '00' else ',' + frac} $"


class Offer:
    def __init__(self, price=None, data=None):
        _register_fonts()
        self.data = data if data is not None else offer_data(price)
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

    def text(
        self,
        x,
        top,
        s,
        *,
        size,
        bold=False,
        color=DARK,
        align="l",
        space=0.0,
        max_w=None,
        font=None,
    ):
        font = font or ("Mont-Bold" if bold else "Mont")
        s = str(s)
        while max_w and size > 8 and self.width(s, size, bold, space, font) > max_w:
            size -= 1
        w = self.width(s, size, bold, space, font)
        if align == "c":
            x -= w / 2
        elif align == "r":
            x -= w
        self.c.setFillColor(color)
        self.c.setFont(font, size)
        self.c.drawString(x, self.y(top), s, charSpace=space)
        return w

    def heading(
        self, x, top, bold_part, rest="", *, size=T_PAGE, align="l", color=FOREST, max_w=None
    ):
        """«БИЗ ҲАҚИМИЗДА»-style title: the first word bold, the rest regular."""
        gap = size * 0.28 if rest else 0
        while (
            max_w
            and size > 20
            and (self.width(bold_part, size, True) + gap + self.width(rest, size) > max_w)
        ):
            size -= 2
            gap = size * 0.28 if rest else 0
        wa, wb = self.width(bold_part, size, True), self.width(rest, size) if rest else 0
        x0 = x - (wa + gap + wb) / 2 if align == "c" else x
        self.text(x0, top, bold_part, size=size, bold=True, color=color)
        if rest:
            self.text(x0 + wa + gap, top, rest, size=size, color=DARK)
        return wa + gap + wb

    def room_title(self, room, rest="", cont=False):
        """Every room page starts the same way: grey page, title top-left, a short rule."""
        self.fill_page(GREY_BG)
        rest = (rest + (" (давоми)" if cont else "")).strip()
        self.heading(
            ROOM_X, ROOM_TOP, room["name"].upper(), rest, size=T_ROOM, max_w=W - 2 * ROOM_X
        )
        self.c.setStrokeColor(GREEN)
        self.c.setLineWidth(4)
        self.c.line(ROOM_X, self.y(ROOM_TOP + 22), ROOM_X + 70, self.y(ROOM_TOP + 22))

    @staticmethod
    def width(s, size, bold=False, space=0.0, font=None):
        font = font or ("Mont-Bold" if bold else "Mont")
        return pdfmetrics.stringWidth(str(s), font, size) + space * max(len(str(s)) - 1, 0)

    def paragraphs(self, x, top, width, paras, *, size=T_BODY, leading=None, gap=10, color=DARK):
        """Text-page paragraphs in Montserrat Medium; a «**lead-in:**» is SemiBold and a
        «— item» line is indented like a list."""
        leading = leading or size * 1.5
        body, semi = "Mont-Medium", "Mont-Semi"
        cy = top
        for p in paras:
            px, pw = x, width
            if p.startswith("— "):
                self.text(x + 4, cy, "•", size=size, font=semi, color=GREEN)
                px, pw, p = x + 24, width - 24, p[2:]
            head = ""
            if p.startswith("**"):
                end = p.find("**", 2)
                head, p = p[2:end], p[end + 2 :].lstrip()
            lines = simpleSplit(p, body, size, pw) if p else []
            if head:
                hw = self.text(px, cy, head, size=size, font=semi, color=color) + size * 0.3
                first = simpleSplit(p, body, size, pw - hw)[:1] if p else []
                if first:
                    self.text(px + hw, cy, first[0], size=size, font=body, color=color)
                    rest = p[len(first[0]) :].lstrip()
                    lines = simpleSplit(rest, body, size, pw) if rest else []
                else:
                    lines = []
                cy += leading
            for line in lines:
                self.text(px, cy, line, size=size, font=body, color=color)
                cy += leading
            cy += gap
        return cy

    def logo(self, x, top, w):
        """The crisp logo over where the template's blurry one was (erased from the
        backgrounds)."""
        img = ImageReader(str(HERE / "logo.png"))
        iw, ih = img.getSize()
        h = w * ih / iw
        self.c.drawImage(img, x, self.y(top + h), w, h, mask="auto")

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
        self.logo(81, 40, 140)
        self.text(1385, 60, "СМЕТАЧИ", size=T_LABEL, color=MUTED, align="r", space=1)
        self.text(
            1385, 88, (d["estimator"] or "SERMEBEL").upper(), size=T_BODY, bold=True, align="r"
        )
        self.text(1385, 114, d["date"].strftime("%d.%m.%Y"), size=T_LABEL, color=MUTED, align="r")
        self.heading(W / 2, 262, "ТИЖОРАТ", "ТАКЛИФИ", size=T_HERO, align="c", color=DARK)
        self.text(W / 2, 308, "ХУРМАТЛИ", size=30, align="c", space=7)
        if d["client"]:
            self.text(W / 2, 354, d["client"].upper(), size=30, align="c", space=7, max_w=900)

    def about(self):
        self.bg("bg_about.png")
        self.logo(81, 30, 110)
        self.heading(82, 172, "БИЗ", "ҲАҚИМИЗДА")
        self.paragraphs(82, 236, 590, ABOUT, size=T_BODY + 1, gap=16)
        self.url_box(98, 700, 495)

    @staticmethod
    def photos(room):
        """Renders / drawings of the whole room (furniture pictures go to their cards)."""
        return [(f, "") for f in room["images"]]

    @staticmethod
    def item_photos(it):
        """A furniture card's pictures: its own, then its accessories' (captioned)."""
        out = [(f, "") for f in it.get("images") or []]
        for a in it.get("accessories") or []:
            if a.get("image"):
                out.append((a["image"], a["name"]))
        return out

    def room_photos(self, room):
        imgs = []
        for f, caption in self.photos(room):
            loaded = self._load(f)
            if loaded:
                imgs.append((*loaded, caption))
        for start in range(0, len(imgs), 6):
            chunk = imgs[start : start + 6]
            self.room_title(room, cont=bool(start))
            n = len(chunk)
            split = {1: [1], 2: [2], 3: [3], 4: [2, 2], 5: [3, 2]}.get(n, [3, 3])
            rows, i = [], 0
            for k in split:
                rows.append(chunk[i : i + k])
                i += k
            # every row: same height for all its pictures, as wide as the page allows;
            # a row with captions keeps room for one line of text under the pictures
            aw, ah, gap, top = W - 2 * ROOM_X, H - 160 - 50, 24, 160
            caps = [32 if any(x[3] for x in r) else 0 for r in rows]
            row_ah = (ah - gap * (len(rows) - 1) - sum(caps)) / len(rows)
            heights = [
                min(row_ah, (aw - gap * (len(r) - 1)) / sum(iw / ih for _, iw, ih, _ in r))
                for r in rows
            ]
            used = sum(heights) + sum(caps) + gap * (len(rows) - 1)
            cy = top + (ah - used) / 2
            c = self.c
            for r, h, cap in zip(rows, heights, caps):
                widths = [h * iw / ih for _, iw, ih, _ in r]
                cx = (W - sum(widths) - gap * (len(r) - 1)) / 2
                for (reader, _, _, caption), w in zip(r, widths):
                    c.saveState()
                    p = c.beginPath()
                    p.roundRect(cx, self.y(cy + h), w, h, 14)
                    c.clipPath(p, stroke=0, fill=0)
                    c.drawImage(reader, cx, self.y(cy + h), w, h)
                    c.restoreState()
                    if caption:
                        self.text(
                            cx + w / 2,
                            cy + h + 24,
                            caption.upper(),
                            size=T_LABEL,
                            bold=True,
                            align="c",
                            max_w=w,
                        )
                    cx += w + gap
                cy += h + cap + gap
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

    # Furniture cards: a piece of furniture with pictures gets its own row — the pictures
    # on the left, what it is made of and its price on the right.
    CARD_W, IMG_W, LABEL_W = W - 2 * ROOM_X, 600, 200
    BODY_TOP = 165

    def item_cards(self, room):
        cards = []
        for it in room["items"]:
            imgs = []
            for f, caption in self.item_photos(it):
                loaded = self._load(f)
                if loaded:
                    imgs.append((*loaded, caption))
            if imgs:
                info = self._card_info(it)
                cards.append((it, imgs, info))
        if not cards:
            return
        limit, gap = H - self.BODY_TOP - 40, 24
        pages, cur, used = [], [], 0
        for it, imgs, info in cards:
            h = max(290, min(info[0], limit))
            if cur and used + h > limit:
                pages.append(cur)
                cur, used = [], 0
            cur.append((it, imgs, info, h))
            used += h + gap
        pages.append(cur)
        for pi, chunk in enumerate(pages):
            self.room_title(room, "МЕБЕЛЛАР", cont=pi > 0)
            cy = self.BODY_TOP
            for it, imgs, info, h in chunk:
                self._card(it, imgs, info, cy, h)
                cy += h + gap
            self.c.showPage()

    def _card_info(self, it):
        info_w = self.CARD_W - self.IMG_W - 94
        name_lines = simpleSplit(it["name"].upper(), "Mont-Bold", T_ITEM + 4, info_w)
        rows = []
        for ln in offer_lines(it):
            lab = simpleSplit(ln["label"].upper(), "Mont", T_LABEL, self.LABEL_W - 16)
            val = simpleSplit(str(ln["value"]), "Mont", T_VALUE, info_w - self.LABEL_W)
            rows.append((lab, val))
        h = 28 + len(name_lines) * 27 + (22 if measure_text(it) else 0) + 12
        h += sum(max(len(a), len(b)) * 20 + 8 for a, b in rows)
        h += 84  # price strip
        return h, name_lines, rows

    def _card(self, it, imgs, info, top, h):
        c = self.c
        x, cw = ROOM_X, self.CARD_W
        _, name_lines, rows = info
        c.setFillColor(white)
        c.setStrokeColor(LINE)
        c.setLineWidth(1)
        c.roundRect(x, self.y(top + h), cw, h, 14, stroke=1, fill=1)
        # pictures: one row, same height, centred in the left part
        pad, gap = 20, 14
        aw, ah = self.IMG_W, h - 2 * pad
        cap = 24 if any(i[3] for i in imgs) else 0
        imgs = imgs[:4]
        rh = min(ah - cap, (aw - gap * (len(imgs) - 1)) / sum(iw / ih for _, iw, ih, _ in imgs))
        widths = [rh * iw / ih for _, iw, ih, _ in imgs]
        ix = x + pad + (aw - sum(widths) - gap * (len(imgs) - 1)) / 2
        iy = top + pad + (ah - rh - cap) / 2
        for (reader, _, _, caption), w in zip(imgs, widths):
            c.saveState()
            p = c.beginPath()
            p.roundRect(ix, self.y(iy + rh), w, rh, 10)
            c.clipPath(p, stroke=0, fill=0)
            c.drawImage(reader, ix, self.y(iy + rh), w, rh)
            c.restoreState()
            if caption:
                self.text(
                    ix + w / 2,
                    iy + rh + 18,
                    caption.upper(),
                    size=T_LABEL - 1,
                    bold=True,
                    align="c",
                    max_w=w,
                )
            ix += w + gap
        # info
        x0 = x + pad + self.IMG_W + 34
        c.setStrokeColor(LINE)
        c.line(x0 - 17, self.y(top + pad), x0 - 17, self.y(top + h - pad))
        y = top + 28 + 20
        for ln in name_lines:
            self.text(x0, y, ln, size=T_ITEM + 4, bold=True)
            y += 27
        if measure_text(it):
            self.text(x0, y - 4, measure_text(it), size=T_LABEL + 1, color=MUTED)
            y += 22
        y += 10
        bottom = top + h - 84
        for lab, val in rows:
            if y + 14 > bottom:
                break
            ly = y
            for t in lab:
                self.text(x0, ly, t, size=T_LABEL, color=MUTED)
                ly += 20
            vy = y
            for t in val:
                self.text(x0 + self.LABEL_W, vy, t, size=T_VALUE)
                vy += 20
            y = max(ly, vy) + 8
        # price strip
        c.setStrokeColor(LINE)
        c.line(x0, self.y(top + h - 70), x + cw - pad, self.y(top + h - 70))
        self.text(x0, top + h - 30, "НАРХИ", size=T_LABEL, color=MUTED, space=1)
        self.text(
            x + cw - 30,
            top + h - 26,
            money(it["amount"]),
            size=T_TOTAL + 4,
            bold=True,
            color=GREEN,
            align="r",
        )

    # The price table: МЕБЕЛ | МАТЕРИАЛЛАР | НАРХИ, one block per furniture item,
    # every «label: material» on its own aligned row.
    TX, TW = 80, 1280
    C1, C2 = 400, 1040  # column borders (x from TX)
    ROW_H, PAD = 27, 14

    def room_prices(self, room):
        blocks = [self._block(it) for it in room["items"]]
        page_blocks, cur, used = [], [], 0
        room_h = H - self.BODY_TOP - 56 - 64 - 40  # header 56, total row 64, bottom margin
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
        name_lines = simpleSplit(name, "Mont-Bold", T_ITEM, self.C1 - 30)
        rows = []
        for p in offer_lines(it):
            label_lines = simpleSplit(f"{p['label'].upper()}:", "Mont", T_LABEL, self.C1 - 30)
            value_lines = simpleSplit(
                str(p["value"]).upper(), "Mont", T_VALUE, self.C2 - self.C1 - 40
            )
            rows.append((label_lines, value_lines))
        h = self.PAD * 2 + len(name_lines) * 22
        if measure_text(it):
            h += 20
        for lab, val in rows:
            h += max(len(lab), len(val)) * self.ROW_H * 0.8 + 6
        return (max(h, 70), it, name_lines, rows)

    def _price_page(self, room, blocks, last, cont):
        c = self.c
        self.room_title(room, "НАРХИ", cont=cont)
        tx, tw = self.TX, self.TW
        top = self.BODY_TOP
        body_h = sum(b[0] for b in blocks) + (64 if last else 0)
        # card
        c.setFillColor(white)
        c.setStrokeColor(LINE)
        c.setLineWidth(1)
        c.roundRect(tx, self.y(top + 56 + body_h), tw, 56 + body_h, 14, stroke=1, fill=1)
        # header
        c.saveState()
        p = c.beginPath()
        p.roundRect(tx, self.y(top + 56 + body_h), tw, 56 + body_h, 14)
        c.clipPath(p, stroke=0, fill=0)
        c.setFillColor(HEAD)
        c.rect(tx, self.y(top + 56), tw, 56, stroke=0, fill=1)
        c.restoreState()
        for label, x0, x1 in (
            ("МЕБЕЛ", 0, self.C1),
            ("МАТЕРИАЛЛАР", self.C1, self.C2),
            ("НАРХИ", self.C2, tw),
        ):
            self.text(
                tx + (x0 + x1) / 2,
                top + 35,
                label,
                size=T_LABEL + 2,
                bold=True,
                color=white,
                align="c",
                space=2,
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
                self.text(tx + self.C1 / 2, y, ln, size=T_ITEM, bold=True, color=DARK, align="c")
                y += 22
            if measure_text(it):
                self.text(
                    tx + self.C1 / 2,
                    y - 2,
                    f"({measure_text(it)})",
                    size=T_LABEL,
                    color=MUTED,
                    align="c",
                )
                y += 20
            y += 4
            for lab, val in rows:
                ly = y
                for ln in lab:
                    self.text(tx + self.C1 / 2, ly, ln, size=T_LABEL, color=MUTED, align="c")
                    ly += self.ROW_H * 0.8
                vy = y
                for ln in val:
                    self.text(
                        tx + (self.C1 + self.C2) / 2, vy, ln, size=T_VALUE, color=DARK, align="c"
                    )
                    vy += self.ROW_H * 0.8
                y = max(ly, vy) + 6
            self.text(
                tx + (self.C2 + tw) / 2,
                cy + h / 2 + 8,
                money(it["amount"]),
                size=T_PRICE,
                bold=True,
                align="c",
            )
            cy += h
        if last:
            c.setFillColor(HexColor("#EEF7F1"))
            c.saveState()
            p = c.beginPath()
            p.roundRect(tx, self.y(top + 56 + body_h), tw, 56 + body_h, 14)
            c.clipPath(p, stroke=0, fill=0)
            c.rect(tx, self.y(cy + 64), tw, 64, stroke=0, fill=1)
            c.restoreState()
            c.setStrokeColor(LINE)
            c.setLineWidth(1)
            c.line(tx, self.y(cy), tx + tw, self.y(cy))
            self.text(
                tx + self.C2 - 30, cy + 41, "ЖАМИ:", size=T_PRICE, bold=True, color=GREEN, align="r"
            )
            self.text(
                tx + (self.C2 + tw) / 2,
                cy + 42,
                money(room["total"]),
                size=T_TOTAL,
                bold=True,
                color=GREEN,
                align="c",
            )
        c.showPage()

    def total(self):
        d = self.data
        self.bg("bg_total.png")
        self.logo(81, 30, 110)
        top = 175
        self.heading(W / 2, top, "УМУМИЙ", "ЖАМИ", align="c")
        if d["variant"]:
            top += 70
            self.text(
                W / 2,
                top,
                d["variant"].upper(),
                size=T_ROOM,
                bold=True,
                color=FOREST,
                align="c",
                space=4,
                max_w=1100,
            )
        rooms = [r for r in d["rooms"] if r["items"]]
        size = T_BODY + 2 if len(rooms) <= 10 else T_LABEL + 1
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
            f"ЖАМИ — {money(d['total'])}",
            size=32,
            bold=True,
            color=white,
            align="c",
        )

    def delivery(self):
        self.bg("bg_delivery.png")
        self.logo(81, 30, 110)
        self.text(758, 150, "ЕТКАЗИБ БЕРИШ", size=T_PAGE, bold=True, color=FOREST, max_w=620)
        self.text(758, 222, "ВА ЎРНАТИШ", size=T_PAGE, color=DARK, max_w=620)
        self.paragraphs(758, 290, 600, DELIVERY, size=T_BODY, gap=8)
        self.text(800, 720, f"http://{SITE}", size=17, bold=True)

    def terms(self):
        self.bg("bg_terms.png")
        self.logo(81, 30, 110)
        self.text(98, 172, "ТАЙЁРЛАШ", size=T_PAGE, bold=True, color=FOREST)
        self.text(98, 240, "МУДДАТИ", size=T_PAGE, color=DARK)
        self.paragraphs(98, 296, 600, TERMS, size=T_BODY, gap=7)

    def thanks(self):
        self.bg("bg_thanks.png")
        self.logo(81, 22, 140)
        c = self.c
        c.setFillColor(white)  # hide the contacts baked into the background (old phone)
        c.rect(140, self.y(740), 420, 175, stroke=0, fill=1)
        self.text(90, 312, "РАҲМАТ,", size=T_HERO + 4, bold=True)
        for i, line in enumerate(("СИФАТ ВА УСЛУБНИ", "БИЗ БИЛАН", "ТАНЛАГАНИНГИЗ УЧУН")):
            # the sofa's circle starts at ~x 560: keep the lines left of it
            self.text(90, 378 + i * 50, line, size=34, max_w=440)
        for top, s in ((581, TELEGRAM), (622, INSTAGRAM), (664, PHONE), (707, ADDRESS)):
            self.text(150, top, s, size=T_LABEL + 1)
        self.text(167, 777, f"http://{SITE}", size=18, bold=True)

    def build(self) -> bytes:
        for page in (self.cover, self.about):
            page()
            self.c.showPage()
        for room in self.data["rooms"]:
            if self.photos(room):
                self.room_photos(room)
            self.item_cards(room)
            if room["items"]:
                self.room_prices(room)
        for page in (self.total, self.delivery, self.terms, self.thanks):
            page()
            self.c.showPage()
        self.c.save()
        return self.buf.getvalue()


def build_offer_pdf(price=None, data=None) -> bytes:
    """`data`: a saved version (services.version_offer_data) instead of the live price."""
    return Offer(price, data).build()
