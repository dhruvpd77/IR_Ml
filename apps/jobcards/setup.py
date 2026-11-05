from django.db import transaction
from django.utils.text import slugify

from jobcards.models import JobCardField, JobCardTemplate


def new_template_version(template, user):
    template.is_active = False
    template.save(update_fields=["is_active"])
    clone = JobCardTemplate.objects.create(
        phase_code=template.phase_code,
        name=template.name,
        description=template.description,
        version=template.version + 1,
        is_active=True,
        created_by=user,
    )
    for field in template.fields.all():
        field.pk = None
        field.id = None
        field.template = clone
        field.save()
    return clone


def replace_fields(template, specs):
    with transaction.atomic():
        if template.submissions.exists():
            raise ValueError("This template already has submissions. Create a new version before replacing its fields.")
        template.fields.all().delete()
        for index, spec in enumerate(specs, start=1):
            JobCardField.objects.create(template=template, sort_order=index, **spec)


def unique_key(template, label, taken):
    base = (slugify(label) or "field")[:70]
    key = base
    number = 2
    while key in taken or template.fields.filter(field_key=key).exists():
        key = f"{base[:60]}-{number}"
        number += 1
    taken.add(key)
    return key
