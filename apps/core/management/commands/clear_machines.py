"""Erase every registered machine and related shop data. Users stay.

Keeps: users, departments, stations, phases, job-card templates,
model catalog, logos, settings, tentative month plans.

Removes: machines, planning rows, phase states, job-card submissions,
attachments (local + S3), rework, workflow events, machine notes,
import batches, machine notifications, and resets the IR-MCH sequence.

On PythonAnywhere:

    python manage.py clear_machines --confirm CLEAR-MACHINES
"""

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from audit.models import AuditLog
from jobcards.models import JobCardSubmission, MachineAttachment
from machines.models import ImportBatch, Machine, MachineNote, MachineSequence
from notifications.models import Notification
from rework.models import ReworkRequest
from workflow.models import MachinePhaseState, WorkflowEvent

CONFIRM = "CLEAR-MACHINES"


class Command(BaseCommand):
    help = "Delete all machines and related records. Users and setup stay."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            required=True,
            help=f'Must be exactly "{CONFIRM}" to run.',
        )
        parser.add_argument(
            "--keep-audit",
            action="store_true",
            help="Do not delete audit log rows.",
        )

    def handle(self, *args, **options):
        if options["confirm"] != CONFIRM:
            raise CommandError(f'Type --confirm {CONFIRM} to erase all machine data.')

        before = Machine.objects.count()
        attachments = MachineAttachment.objects.count()
        self.stdout.write(
            f"About to erase {before} machine(s) and {attachments} attachment(s). Users will stay."
        )

        removed_files = 0
        for attachment in MachineAttachment.objects.iterator():
            name = ""
            try:
                name = attachment.file.name if attachment.file else ""
                if attachment.file:
                    attachment.file.delete(save=False)
                    removed_files += 1
            except Exception as exc:
                self.stderr.write(f"Could not delete file {name or attachment.pk}: {exc}")
                if name:
                    try:
                        if default_storage.exists(name):
                            default_storage.delete(name)
                            removed_files += 1
                    except Exception:
                        pass

        with transaction.atomic():
            # Explicit deletes first so PROTECT links never block a machine wipe.
            MachineAttachment.objects.all().delete()
            JobCardSubmission.objects.all().delete()
            ReworkRequest.objects.all().delete()
            WorkflowEvent.objects.all().delete()
            MachinePhaseState.objects.all().delete()
            MachineNote.objects.all().delete()
            Notification.objects.filter(machine__isnull=False).delete()
            ImportBatch.objects.all().delete()
            deleted, _details = Machine.objects.all().delete()
            MachineSequence.objects.update_or_create(pk=1, defaults={"last_number": 0})
            if not options["keep_audit"]:
                AuditLog.objects.all().delete()

        left = Machine.objects.count()
        if left:
            raise CommandError(f"Wipe incomplete. {left} machine(s) still remain.")

        self.stdout.write(
            self.style.SUCCESS(
                f"Fresh start ready. Removed {before} machines, deleted about {removed_files} media files, "
                f"ORM deleted {deleted} related rows. Next machine id will be IR-MCH-000001. "
                f"Users, stations, phases, templates, and model catalog are still here."
            )
        )
