"""Load model→job-card catalog and Assembly/Testing templates from Excel + Word."""

from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError

from jobcards.checklist_import import import_checklists_workbook
from jobcards.word_checklist_import import default_word_folder, import_word_job_cards
from machines.catalog import CatalogError, replace_catalog


class Command(BaseCommand):
    help = (
        "Import Model Wise Category (job_card_key + Word/Excel), UPDATED Production Checklists "
        "(Excel Assembly/Testing), and Word job cards from jobcard_word_file/."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--catalog",
            default="Model Wise Category with job card.xlsx",
            help="Path to Model Wise Category workbook (relative to project root by default).",
        )
        parser.add_argument(
            "--checklists",
            default="UPDATED Production Checklists JAN-2025(copy).xlsx",
            help="Path to Production Checklists workbook.",
        )
        parser.add_argument(
            "--word-folder",
            default="",
            help="Folder of Word job cards (default: jobcard_word_file/).",
        )
        parser.add_argument("--skip-catalog", action="store_true")
        parser.add_argument("--skip-checklists", action="store_true")
        parser.add_argument("--skip-word", action="store_true")

    def handle(self, *args, **options):
        from django.conf import settings

        root = Path(settings.BASE_DIR)
        if not options["skip_catalog"]:
            catalog_path = Path(options["catalog"])
            if not catalog_path.is_absolute():
                catalog_path = root / catalog_path
            if not catalog_path.exists():
                raise CommandError(f"Catalog workbook not found: {catalog_path}")
            data = catalog_path.read_bytes()
            upload = SimpleUploadedFile(
                catalog_path.name,
                data,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            try:
                result = replace_catalog(upload, user=None)
            except CatalogError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(
                self.style.SUCCESS(
                    f"Catalog: {result['created']} models loaded ({result['skipped']} skipped)."
                )
            )

        if not options["skip_checklists"]:
            checklists_path = Path(options["checklists"])
            if not checklists_path.is_absolute():
                checklists_path = root / checklists_path
            if not checklists_path.exists():
                raise CommandError(f"Checklists workbook not found: {checklists_path}")
            result = import_checklists_workbook(checklists_path)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Excel checklists: {result['sheets']} sheets → "
                    f"{result['created']} created, {result['updated']} updated, "
                    f"{result['empty']} empty phases."
                )
            )
            missing_details = [row for row in result["details"] if row["status"] == "empty"]
            if missing_details:
                self.stdout.write(
                    self.style.WARNING(f"{len(missing_details)} empty phase parses (see details).")
                )

        if not options["skip_word"]:
            word_folder = Path(options["word_folder"]) if options["word_folder"] else default_word_folder()
            if not word_folder.is_absolute():
                word_folder = root / word_folder
            try:
                result = import_word_job_cards(word_folder)
            except Exception as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(
                self.style.SUCCESS(
                    f"Word job cards: {result['keys']} names → "
                    f"{result['created']} created, {result['updated']} updated, "
                    f"{result['empty']} empty."
                )
            )
            if result["missing"]:
                self.stdout.write(
                    self.style.WARNING("Missing Word files for: " + ", ".join(result["missing"]))
                )
            errors = [row for row in result["details"] if row.get("status") == "error"]
            for row in errors:
                self.stdout.write(self.style.ERROR(f"{row['key']}: {row.get('error')}"))
