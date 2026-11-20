"""Detailing part of the bot: the task card the detailers get when an order is sent to
detailing (deadline, client, «✅ Bajardim» opens the job on the site).

No router: importing the package registers the `detailing.*` /notify renderers.
"""

from __future__ import annotations

from . import notify  # noqa: F401  (registers detailing.*)
