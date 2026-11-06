"""Copy existing local media files into the configured default storage (S3).

Run on PythonAnywhere after USE_S3=true is set and the web app reloads:

    python manage.py migrate_media_to_s3
    python manage.py migrate_media_to_s3 --delete-local

Does not change database rows. File names stay the same.
"""

from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Copy files from MEDIA_ROOT into the active storage backend (S3)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete-local",
            action="store_true",
            help="Delete each local file only after it is confirmed on S3.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List what would be copied without uploading.",
        )

    def handle(self, *args, **options):
        if not getattr(settings, "USE_S3", False):
            raise CommandError("Turn on USE_S3 and reload the app before migrating media.")
        root = Path(settings.MEDIA_ROOT)
        if not root.exists():
            self.stdout.write("No local media folder found. Nothing to copy.")
            return
        copied = skipped = missing = 0
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            name = path.relative_to(root).as_posix()
            if default_storage.exists(name):
                skipped += 1
                if options["delete_local"] and not options["dry_run"]:
                    path.unlink(missing_ok=True)
                continue
            if options["dry_run"]:
                self.stdout.write(f"Would copy {name}")
                copied += 1
                continue
            try:
                with path.open("rb") as handle:
                    saved = default_storage.save(name, File(handle, name=path.name))
                if not default_storage.exists(saved):
                    missing += 1
                    self.stderr.write(f"Upload failed for {name}")
                    continue
                copied += 1
                if options["delete_local"]:
                    path.unlink(missing_ok=True)
                if copied % 25 == 0:
                    self.stdout.write(f"Copied {copied}...")
            except Exception as exc:
                missing += 1
                self.stderr.write(f"Could not copy {name}: {exc}")
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Copied {copied}, already on S3 {skipped}, failed {missing}."
            )
        )
