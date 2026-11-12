"""Test helper: a Molyar job whose whole square is one team's part (what the old
`Painter(type=...)` meant)."""

from order.painter.models import Painter, PainterPart


def make_painter(*, type=None, **kwargs) -> Painter:
    painter = Painter.objects.create(**kwargs)
    if type is not None:
        PainterPart.objects.create(painter=painter, type=type, square=painter.square)
    return painter
