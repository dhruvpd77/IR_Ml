from jobcards.services import active_template


def sample_answers(user, phase_code, machine=None):
    answers = {}
    for field in active_template(phase_code, machine).active_fields():
        kind = field.field_type
        if kind == "pass_fail":
            answers[field.field_key] = "Pass"
        elif kind == "yes_no":
            answers[field.field_key] = "Yes"
        elif kind in {"measurement", "decimal"}:
            answers[field.field_key] = "12.5"
        elif kind == "integer":
            answers[field.field_key] = "4"
        elif kind == "signature":
            answers[field.field_key] = {"name": user.display_name, "confirmed": True}
        elif kind in {"dropdown", "radio"}:
            answers[field.field_key] = (field.options or ["OK"])[0]
        elif kind == "date":
            answers[field.field_key] = "2026-11-04"
        elif kind in {"image", "video", "file"}:
            continue
        else:
            answers[field.field_key] = "Within specification."
    return answers
