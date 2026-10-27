"""Import the Apps Script davomat (the «Davomat» + «DavomatExport» sheets).

    python manage.py import_davomat_sheet --xlsx SerMebel.xlsx --dry-run
    python manage.py import_davomat_sheet --xlsx SerMebel.xlsx
    python manage.py import_davomat_sheet --sheet-id 1AbC... --credentials sa.json

Run docs/davomat_export.gs in the Apps Script first so «DavomatExport» exists.
Safe to re-run. Finance sheets are never read here.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounting.importer import GoogleSource, XlsxSource
from hr.importer import DavomatImporter


class DryRun(Exception):
    pass


class Command(BaseCommand):
    help = "Google jadvaldagi davomat ma'lumotlarini bazaga import qilish (moliya varaqlariga tegmaydi)."

    def add_arguments(self, parser):
        parser.add_argument("--xlsx")
        parser.add_argument("--sheet-id")
        parser.add_argument("--credentials")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, xlsx=None, sheet_id=None, credentials=None, dry_run=False, **opts):
        if bool(xlsx) == bool(sheet_id):
            raise CommandError("--xlsx yoki --sheet-id dan bittasini bering.")
        if sheet_id and not credentials:
            raise CommandError("--sheet-id uchun --credentials kerak.")
        source = XlsxSource(xlsx) if xlsx else GoogleSource(sheet_id, credentials)
        report = None
        try:
            with transaction.atomic():
                report = DavomatImporter(source).run()
                if dry_run:
                    raise DryRun()
        except DryRun:
            self.stdout.write(self.style.WARNING("DRY RUN — hech narsa saqlanmadi."))
        self.stdout.write(report.text())
        if report.ok():
            self.stdout.write(self.style.SUCCESS("Hammasi mos keldi."))
        else:
            self.stdout.write(self.style.ERROR("Tekshiruvda farq bor — ❌ qatorlarni ko'ring."))
