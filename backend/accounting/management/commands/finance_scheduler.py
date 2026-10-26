"""Runs the finance bot's scheduled jobs (reminders, daily reports, Готов follow-up).

python manage.py finance_scheduler          # loop forever (docker "scheduler" service)
python manage.py finance_scheduler --once   # one pass (cron / manual test)
"""

import logging
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from accounting.jobs import run_due

log = logging.getLogger("finance.jobs")


class Command(BaseCommand):
    help = "Moliya botining rejali vazifalari (eslatmalar, hisobotlar, Готов kuzatuvi)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Bir marta ishlatib chiqish")
        parser.add_argument("--interval", type=int, default=60, help="Tekshirish oralig'i, soniya")

    def handle(self, *args, once=False, interval=60, **opts):
        while True:
            close_old_connections()
            try:
                ran = run_due()
                if ran:
                    self.stdout.write(f"ran: {', '.join(ran)}")
            except Exception:  # noqa: BLE001 — keep the loop alive (DB restart etc.)
                log.exception("scheduler pass failed")
            if once:
                return
            time.sleep(max(10, interval))
