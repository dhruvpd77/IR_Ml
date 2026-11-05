from django.core.exceptions import PermissionDenied

from core.constants import PHASE_ROLE, Roles


def can_operate_phase(user, phase_code):
    if not user.is_authenticated:
        return False
    if user.is_management:
        return True
    return user.role == PHASE_ROLE.get(phase_code)


def assert_phase_operator(user, phase_code):
    if not can_operate_phase(user, phase_code):
        raise PermissionDenied("You do not have permission to perform this production action.")


def can_view_machine(user, machine):
    if not user.is_authenticated:
        return False
    if user.is_management:
        return True
    if machine.status == "DRAFT" and machine.created_by_id != user.id:
        return False
    return True


def can_delete_machine(user, machine):
    if not user.is_authenticated:
        return False
    if user.is_management:
        return True
    return (
        user.role == Roles.PLANNING_DATA_ENTRY
        and machine.created_by_id == user.id
        and machine.status == "DRAFT"
    )


def can_edit_planning(user, machine):
    if not user.is_authenticated:
        return False
    if user.is_management:
        return True
    if user.role != Roles.PLANNING_DATA_ENTRY or machine.created_by_id != user.id:
        return False
    if machine.status == "DRAFT":
        return True
    return machine.phase_states.filter(phase__code="PLANNING", status="IN_PROGRESS").exists()


def can_manage_users(user):
    return user.is_authenticated and user.is_management


def can_view_reports(user):
    if not user.is_authenticated:
        return False
    return user.is_management or user.role in {
        Roles.PRODUCTION_LEADER,
        Roles.QC,
    }


def can_reject(user, machine):
    if not user.is_authenticated or not getattr(machine, "pk", None):
        return False
    machine.refresh_from_db(fields=["status"])
    if machine.status == "DRAFT":
        return False
    if user.is_management:
        return True
    if user.role == Roles.QC and machine.phase_states.filter(phase__code="QC", status="IN_PROGRESS").exists():
        return True
    return False
