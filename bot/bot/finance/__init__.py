"""Finance (Moliya) bot: handlers over the backend API, `finance.*` notification
renderers (imported for their `@on` registration) and the router."""

from bot.finance import notify  # noqa: F401  (registers the finance.* events)
from bot.finance.handlers.menu import finance_start
from bot.finance.router import make_router, router

__all__ = ["finance_start", "make_router", "router"]
