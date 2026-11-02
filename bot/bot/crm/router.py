"""The CRM Router: task buttons first, then the lead form. Sits after `common.start` and
before the HR private router and finance, so «🆕 Yangi mijoz», forwards of lead-adders and
`crm:` buttons are taken here and everything else falls through."""

from __future__ import annotations

from aiogram import F, Router

from .handlers import lead, tasks


def make_router() -> Router:
    r = Router(name="crm")
    r.message.filter(F.chat.type == "private")
    r.include_router(tasks.build())
    r.include_router(lead.build())
    return r


router = make_router()
