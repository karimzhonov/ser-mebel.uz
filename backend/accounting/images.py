"""PNG image served to the finance bot: the «Hisob-kitob varaqasi» (the Готов payment sheet).

The charts (donut / bars) moved to the bot service. The sheet is drawn with Pillow. The Apps Script
  built it in Google Slides; the layout coordinates (1225×1178 design px) are the same,
  and an uploaded background (constance FIN_REPORT_TEMPLATE, a media path) replaces the
  drawn base like the old /shablon did.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from constance import config
from django.conf import settings
from PIL import Image, ImageDraw, ImageFont

from .text import cur_name, ddmm, fmt_cur

log = logging.getLogger("finance.images")

FONT_DIR = Path(__file__).resolve().parent / "fonts"


# ---------------------------------------------------------------- hisob-kitob varaqasi
W, H = 1225, 1178
G, MINT, TX = "#0B3D2E", "#E8F3EC", "#2E4A3E"
# [x, y, w, h, align, font px, bold, color] — same boxes as HISOB_BOXES in code.txt
BOXES = {
    "MIJOZ": (296, 316, 420, 34, "l", 24, True, (10, 40, 25)),
    "TUR": (296, 350, 420, 34, "l", 22, True, (10, 40, 25)),
    "SANA": (296, 384, 420, 34, "l", 22, True, (10, 40, 25)),
    "VAL": (860, 450, 286, 34, "c", 21, True, (255, 255, 255)),
    "S1": (862, 502, 272, 36, "r", 22, True, (20, 20, 20)),
    "S2": (862, 550, 272, 36, "r", 22, True, (20, 20, 20)),
    "S3": (862, 601, 272, 38, "r", 22, True, (20, 20, 20)),
    "SUBT": (190, 732, 520, 30, "l", 21, False, (60, 70, 65)),
    "FORMULA": (190, 767, 520, 32, "l", 20, True, (20, 20, 20)),
    "YAKUN": (762, 706, 372, 76, "c", 46, True, (255, 255, 255)),
}


def _font(px: float, bold: bool):
    return ImageFont.truetype(
        str(FONT_DIR / ("Montserrat-Bold.ttf" if bold else "Montserrat-Regular.ttf")), int(px)
    )


def _text(d: ImageDraw.ImageDraw, text, x, y, w, h, px, bold, color, align="l"):
    text = str(text)
    f = _font(px, bold)
    # shrink to fit (Slides had autofit off but the boxes were sized generously)
    while d.textlength(text, font=f) > w and px > 10:
        px -= 1
        f = _font(px, bold)
    tw = d.textlength(text, font=f)
    tx = x if align == "l" else (x + w - tw if align == "r" else x + (w - tw) / 2)
    ty = y + (h - px) / 2 - px * 0.1
    d.text((tx, ty), text, font=f, fill=color)


def _wrap(d, text, x, y, w, px, bold, color, line_h=1.35, align="l"):
    f = _font(px, bold)
    words, line, lines = str(text).split(), "", []
    for wd in words:
        t = (line + " " + wd).strip()
        if d.textlength(t, font=f) <= w:
            line = t
        else:
            lines.append(line)
            line = wd
    lines.append(line)
    for i, ln in enumerate(lines):
        tw = d.textlength(ln, font=f)
        tx = x if align == "l" else x + (w - tw) / 2
        d.text((tx, y + i * px * line_h), ln, font=f, fill=color)


def _base() -> Image.Image:
    bg_path = str(config.FIN_REPORT_TEMPLATE or "").strip()
    if bg_path:
        try:
            p = Path(settings.MEDIA_ROOT) / bg_path
            return Image.open(p).convert("RGB").resize((W, H))
        except Exception:  # noqa: BLE001 — fall back to the drawn design
            log.warning("report background %s not usable", bg_path)
    im = Image.new("RGB", (W, H), "#FFFFFF")
    d = ImageDraw.Draw(im)
    R = lambda x, y, w, h, fill, line=None, r=0: d.rounded_rectangle(  # noqa: E731
        (x, y, x + w, y + h), radius=r, fill=fill, outline=line, width=1 if line else 0
    )
    R(780, 0, 445, 290, MINT)
    _text(d, "SERMEBEL", 780, 70, 445, 50, 36, True, G, "c")
    _text(d, "INTERIOR SOLUTIONS", 780, 120, 445, 30, 16, False, G, "c")
    _text(d, "Orzularingiz uyda boshlanadi", 780, 180, 445, 40, 22, False, TX, "c")
    _text(d, "SerMebel", 56, 34, 700, 100, 86, True, G)
    _text(d, "UYINGIZ UCHUN ENG YAXSHI TANLOV", 62, 128, 700, 26, 17, False, "#333333")
    _text(d, "HISOB-KITOB VARAQASI", 58, 172, 720, 60, 50, True, G)
    _text(d, "Mijoz bo'yicha to'lov ma'lumotlari", 60, 234, 720, 36, 27, False, TX)
    for i, lab in enumerate(["Mijoz:", "Mebel turi:", "Sana:"]):
        _text(d, lab, 60, 316 + 34 * i, 220, 34, 22, False, "#333333")
    R(730, 306, 420, 112, "#F3F8F5", "#C9DCCF", 14)
    _wrap(
        d,
        "Ushbu hisob-kitob shartnoma shartlariga muvofiq amalga oshirildi.",
        750,
        322,
        380,
        18,
        False,
        TX,
    )
    R(60, 446, 1090, 42, G)
    _text(d, "№", 60, 450, 80, 34, 21, True, "#FFFFFF", "c")
    _text(d, "Tavsif", 140, 450, 720, 34, 21, True, "#FFFFFF", "c")
    R(60, 492, 1090, 48, "#FFFFFF", "#E3E8E5")
    R(60, 540, 1090, 50, "#F7F9F8", "#E3E8E5")
    R(60, 590, 1090, 52, MINT, "#E3E8E5")
    for n, lab, y, bold in [
        ("1", "Umumiy summa (shartnoma)", 502, False),
        ("2", "Oldindan to'lov (avans)", 550, False),
        ("3", "Qolgan summa", 601, True),
    ]:
        _text(d, n, 60, y, 80, 36, 22, False, "#222222", "c")
        _text(d, lab, 160, y, 680, 36, 22, bold, "#222222")
    R(60, 676, 1090, 136, MINT, None, 18)
    _text(d, "Yakuniy qoldiq summa:", 190, 690, 540, 40, 30, True, G)
    R(752, 694, 392, 100, G, None, 18)
    R(60, 836, 1090, 110, "#FFFFFF", "#C9DCCF", 18)
    _wrap(
        d,
        "Eslatma: ushbu hisob-kitob mijoz bilan kelishilgan shartlar asosida tuzilgan. Savollaringiz bo'lsa, biz bilan bog'lanishingiz mumkin.",
        84,
        856,
        720,
        18,
        False,
        TX,
    )
    _wrap(d, "Ishonchli hamkorlik — barqaror natijalar!", 820, 866, 310, 18, True, G, align="c")
    _text(
        d,
        "Toshkent, O'zbekiston  ·  +998 55 500 60 09  ·  @sermebel  ·  www.sermebel.uz",
        60,
        964,
        1090,
        40,
        18,
        False,
        "#333333",
        "c",
    )
    R(0, 1036, 1225, 142, G)
    _text(d, "SERMEBEL  ·  INTERIOR SOLUTIONS", 60, 1086, 560, 44, 22, True, "#FFFFFF")
    _text(d, "UYINGIZ UCHUN ENG YAXSHI TANLOV", 620, 1086, 545, 44, 16, False, "#FFFFFF", "r")
    return im


def report_card_png(values: dict) -> bytes:
    """values: MIJOZ, TUR, SANA, VAL, S1, S2, S3, FORMULA, YAKUN (hisobValues_)."""
    im = _base()
    d = ImageDraw.Draw(im)
    values = {"SUBT": "Umumiy summa – Oldindan to'lov", **values}
    for key, (x, y, w, h, al, px, bold, color) in BOXES.items():
        if key in values:
            _text(d, values[key], x, y, w, h, px, bold, color, al)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def card_values(bn, paid) -> dict:
    """The texts of the payment sheet for an OrderBonus (hisobValues_)."""
    from .services import ZERO

    rest = max(ZERO, bn.total - paid)
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
