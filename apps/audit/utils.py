def client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return request.META.get("REMOTE_ADDR")


def log_audit(user, action, instance=None, changes=None, request=None):
    from audit.models import AuditLog

    actor = user if getattr(user, "is_authenticated", False) else None
    AuditLog.objects.create(
        user=actor,
        action=action,
        object_type=instance._meta.label if instance is not None else "",
        object_id="" if instance is None or not instance.pk else str(instance.pk),
        object_repr="" if instance is None else str(instance)[:250],
        changes=changes or {},
        ip_address=client_ip(request),
    )
