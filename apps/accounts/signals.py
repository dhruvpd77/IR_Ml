from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver


@receiver(user_logged_in)
def audit_login(sender, request, user, **kwargs):
    from audit.utils import log_audit

    log_audit(user, "login", instance=user, request=request)


@receiver(user_logged_out)
def audit_logout(sender, request, user, **kwargs):
    from audit.utils import log_audit

    if user is not None:
        log_audit(user, "logout", instance=user, request=request)
