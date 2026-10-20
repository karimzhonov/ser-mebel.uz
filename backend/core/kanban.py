"""Shared plumbing for the admin dashboard's kanban boards.

A board is a list of columns; a column is a queryset filter plus how it should look.
Each app owns its own column definitions and card shape (see `<app>/services.py`);
this module only turns those into render-ready dicts.

Cost is flat in the size of the table: every column's count comes from one
conditional-aggregate query for the whole board, and each column then loads at most
CARDS_PER_COLUMN rows. The overflow is handed to a changelist link rather than
loaded here, so a board with 300 finished orders costs the same as one with 10.

Column filters may only traverse single-valued relations (FK / OneToOne). A
multi-valued join would fan the rows out, which would inflate both the counts and the
card lists — neither the aggregate nor the card query de-duplicates.
"""

from dataclasses import dataclass

from django.db.models import Count, Q, QuerySet

CARDS_PER_COLUMN = 20
# Collapsed columns are hidden until clicked, so they get a token few cards and lean
# on their "open the list" link for the rest.
CARDS_PER_COLLAPSED_COLUMN = 5

# Accent keys; core/static/core/css/kanban.css maps each to a colour in both themes.
IDLE = "idle"
INFO = "info"
WARN = "warn"
OK = "ok"
DANGER = "danger"
PRIMARY = "primary"


@dataclass(frozen=True)
class Column:
    key: str
    title: str
    icon: str
    accent: str
    filters: Q
    # Terminal columns (готов / сотилди / отменён) start folded to a vertical strip so
    # the live part of the flow fits on screen; kanban.js expands them on click.
    collapsed: bool = False
    # Where the footer link points.
    more_url: str = ""
    # Footer wording. Leave empty when more_url selects exactly the same rows as
    # `filters`, and the footer reads "Ещё N →". Set it for a column whose link goes
    # somewhere related but not identical (another model, a looser predicate), so the
    # link never implies a row count it won't deliver.
    more_label: str = ""


def build_board(queryset: QuerySet, columns: list[Column], to_card) -> list[dict]:
    """Render-ready columns for `queryset`, split by each Column's filters."""
    keys = [column.key for column in columns]
    assert len(set(keys)) == len(keys), f"duplicate kanban column keys: {keys}"

    # Aliases are prefixed because a column key may collide with a model field name.
    counts = queryset.aggregate(
        **{f"col_{column.key}": Count("pk", filter=column.filters) for column in columns}
    )

    board = []
    for column in columns:
        total = counts[f"col_{column.key}"]
        limit = CARDS_PER_COLLAPSED_COLUMN if column.collapsed else CARDS_PER_COLUMN
        rows = queryset.filter(column.filters)[:limit]
        more = max(total - limit, 0)

        board.append(
            {
                "key": column.key,
                "title": column.title,
                "icon": column.icon,
                "accent": column.accent,
                "collapsed": column.collapsed,
                "count": total,
                "cards": [to_card(row) for row in rows],
                "more": more,
                "more_url": column.more_url,
                "more_text": column.more_label or f"Ещё {more} →",
                "show_more": bool(column.more_url) and (more > 0 or bool(column.more_label)),
            }
        )
    return board
