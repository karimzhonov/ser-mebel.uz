"""Import the old Google Sheets finance book (Apps Script bot) into the DB.

    python manage.py import_finance_sheet --xlsx SerMebel.xlsx --dry-run
    python manage.py import_finance_sheet --xlsx SerMebel.xlsx
    python manage.py import_finance_sheet --sheet-id 1AbC... --credentials sa.json

Safe to re-run (rows are matched by their ids). See docs/FINANCE_MIGRATION.md.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounting.importer import GoogleSource, Importer, XlsxSource


class DryRun(Exception):
    pass


class Command(BaseCommand):
    help = (
        "Google jadvaldagi moliya ma'lumotlarini bazaga import qilish (Davomat varag'iga tegmaydi)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--xlsx", help="Yuklab olingan .xlsx fayl yo'li")
        parser.add_argument("--sheet-id", help="Google jadval ID (havoladagi /d/<ID>/)")
        parser.add_argument("--credentials", help="Service account JSON fayli (--sheet-id bilan)")
        parser.add_argument(
            "--dry-run", action="store_true", help="Hech narsa saqlamasdan natijani ko'rsatish"
        )

    def handle(self, *args, xlsx=None, sheet_id=None, credentials=None, dry_run=False, **opts):
        if bool(xlsx) == bool(sheet_id):
            raise CommandError("--xlsx yoki --sheet-id dan bittasini bering.")
        if sheet_id and not credentials:
            raise CommandError("--sheet-id uchun --credentials (service account JSON) kerak.")
        source = XlsxSource(xlsx) if xlsx else GoogleSource(sheet_id, credentials)
        report = None
        try:
            with transaction.atomic():
                report = Importer(source).run()
                if dry_run:
                    raise DryRun()
        except DryRun:
            self.stdout.write(self.style.WARNING("DRY RUN — hech narsa saqlanmadi."))
        self.stdout.write(report.text())
        if not report.ok():
            self.stdout.write(
                self.style.ERROR("Tekshiruvda farq bor — yuqoridagi ❌ qatorlarni ko'ring.")
            )
        else:
            self.stdout.write(self.style.SUCCESS("Hammasi mos keldi."))
