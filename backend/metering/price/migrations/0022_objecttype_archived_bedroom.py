"""«Mahsulotlar» clean-up: an object is a kind of furniture, not a room.

«Спальня» was entered as an object; its cards are separate furniture. Here:
- the cards Pod TV / Рабочий стол / Дамская тумба / Комод / Банкетка become their own
  objects (with their products and prices);
- the Матрас / Механизм (подъёмный, массажёр) cards move into «Кровать»;
- the new objects (and Кровать) join every room «Спальня» was listed in;
- «Спальня» is deleted when nothing is left in it, or archived when old calculations
  use it (they keep their lines and stay editable).
Cards that match nothing stay in «Спальня» and it stays visible. Runs once; a
database without «Спальня» is left as it is.
"""

import re

from django.db import migrations, models

SPALNYA = re.compile(r"спальн|spaln", re.I)
KROVAT = re.compile(r"кроват|krovat", re.I)
TO_BED = re.compile(
    r"матра[сц]|matra[st]|механизм|mexanizm|mehanizm|подъ[её]м|podyom|podem|массаж|massaj|massaz",
    re.I,
)
TO_OBJECT = re.compile(
    r"\bтв\b|\btv\b|рабоч|rabochi|стол|\bstol|дамск|damsk|туалетн|комод|komod|kamod|банкет|banket",
    re.I,
)


def reorganize(apps, out=print):
    ObjectType = apps.get_model("price", "ObjectType")
    InventoryType = apps.get_model("price", "InventoryType")
    RoomType = apps.get_model("price", "RoomType")
    Calculate = apps.get_model("price", "Calculate")

    spalnya = next((o for o in ObjectType.objects.order_by("pk") if SPALNYA.search(o.name)), None)
    if spalnya is None:
        return
    # rooms with an explicit list that had «Спальня»; an empty list means «all furniture»
    # and must stay empty
    rooms = list(RoomType.objects.filter(object_types=spalnya))

    def join_rooms(obj):
        for rt in rooms:
            rt.object_types.add(obj)

    krovat = None
    for card in InventoryType.objects.filter(obj=spalnya).order_by("ordering", "pk"):
        if TO_BED.search(card.name):
            if krovat is None:
                krovat = next(
                    (
                        o
                        for o in ObjectType.objects.exclude(pk=spalnya.pk).order_by("pk")
                        if KROVAT.search(o.name)
                    ),
                    None,
                ) or ObjectType.objects.create(name="Кровать", count_name=spalnya.count_name)
                krovat.archived = False
                krovat.save(update_fields=["archived"])
                join_rooms(krovat)
            card.obj = krovat
            card.save(update_fields=["obj"])
            out(f"  «{card.name}» → «{krovat.name}»")
        elif TO_OBJECT.search(card.name):
            name = card.name.strip()
            obj = ObjectType.objects.filter(name__iexact=name).exclude(pk=spalnya.pk).first()
            if obj is None:
                obj = ObjectType.objects.create(
                    name=name, count_name=spalnya.count_name, show_area=spalnya.show_area
                )
            obj.archived = False
            obj.save(update_fields=["archived"])
            join_rooms(obj)
            card.obj = obj
            card.save(update_fields=["obj"])
            out(f"  «{card.name}» → obyekt «{obj.name}»")
        else:
            out(f"  «{card.name}» «{spalnya.name}» ichida qoldi (mos kelmadi)")

    if InventoryType.objects.filter(obj=spalnya).exists():
        out(f"  «{spalnya.name}» qoldi: ichida ko'chirilmagan kartochkalar bor")
    elif Calculate.objects.filter(obj=spalnya).exists():
        spalnya.archived = True
        spalnya.save(update_fields=["archived"])
        out(f"  «{spalnya.name}» arxivlandi (eski hisob-kitoblarda bor)")
    else:
        spalnya.delete()
        out("  «Спальня» o'chirildi")


def forwards(apps, schema_editor):
    reorganize(apps)


class Migration(migrations.Migration):

    dependencies = [
        ("price", "0021_objecttype_show_area"),
    ]

    operations = [
        migrations.AddField(
            model_name="objecttype",
            name="archived",
            field=models.BooleanField(default=False, verbose_name="Arxivda"),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
