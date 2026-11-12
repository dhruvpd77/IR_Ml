from django import template

register = template.Library()


@register.simple_tag
def job_card_for(machine):
    """Resolved Assembly/Testing checklist name for this machine's catalog row."""
    from machines.catalog import (
        job_card_format_for_machine,
        job_card_key_for_machine,
        resolve_checklist_key,
    )

    key = job_card_key_for_machine(machine)
    return resolve_checklist_key(key, job_card_format_for_machine(machine)) or key or ""
