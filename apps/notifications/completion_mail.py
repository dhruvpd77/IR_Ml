"""Email the full job-card PDF when QC completes a machine."""

from __future__ import annotations

import html
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction

from accounts.models import get_setting

logger = logging.getLogger(__name__)


def completion_recipients():
    """Parse one or many recipient emails from Settings (comma or semicolon separated)."""
    raw = (get_setting("completion_email_to", "") or "").strip()
    if not raw:
        return []
    seen = set()
    recipients = []
    for part in raw.replace(";", ",").split(","):
        email = part.strip()
        if not email:
            continue
        key = email.lower()
        if key in seen:
            continue
        seen.add(key)
        recipients.append(email)
    return recipients


def completion_recipient():
    """Back-compat single string used by older checks/UI."""
    return ", ".join(completion_recipients())


def completion_mail_enabled():
    flag = (get_setting("completion_email_enabled", "yes") or "yes").strip().lower()
    return flag in {"1", "true", "yes", "on"} and bool(completion_recipients())


def build_job_card_pdf(machine):
    from reports.pdf import machine_history_pdf
    from workflow.presenters import recent_events, tracking_steps

    submissions = machine.job_card_submissions.select_related("operator", "template").prefetch_related(
        "responses__field", "attachments"
    )
    reworks = machine.reworks.select_related("assigned_phase", "rejected_phase", "rejected_by").prefetch_related("actions")
    events = recent_events(machine, limit=80)
    buffer = machine_history_pdf(machine, tracking_steps(machine), submissions, events, reworks)
    buffer.seek(0)
    return buffer.read()


def _details(machine):
    planning = machine.planning
    machine_name = (getattr(planning, "machine_name", "") or "").strip()
    return [
        ("Machine ID", machine.machine_id),
        ("Machine name", machine_name or "—"),
        ("Work order", planning.work_order or "—"),
        ("Model description", planning.model_description or "—"),
        ("Brand", planning.company or "—"),
        ("Type", planning.machine_type or "—"),
        ("CCN", planning.ccn or "—"),
        ("Serial", machine.planner_serial or machine.production_serial or "—"),
        ("Station", machine.station.code if machine.station_id else "—"),
        ("Approved by", machine.qc_approved_by.display_name if machine.qc_approved_by_id else "—"),
        ("Approved at", machine.qc_approved_at.strftime("%d %b %Y, %H:%M") if machine.qc_approved_at else "—"),
    ]


def _mail_body_text(machine):
    lines = [
        f"{machine.machine_id} has completed Quality Control and is released.",
        "",
    ]
    for label, value in _details(machine):
        lines.append(f"{label}: {value}")
    lines.extend(
        [
            "",
            "The full job card PDF is attached.",
            "",
            "Ingersoll Rand · Production ROTARY",
        ]
    )
    return "\n".join(lines)


def _mail_body_html(machine):
    planning = machine.planning
    rows = []
    for index, (label, value) in enumerate(_details(machine)):
        bg = "#ffffff" if index % 2 == 0 else "#f8fafc"
        rows.append(
            f"""
            <tr>
              <td style="padding:12px 14px;border-bottom:1px solid #e2e8f0;color:#64748b;font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;width:34%;background:{bg};vertical-align:top;">
                {html.escape(label)}
              </td>
              <td style="padding:12px 14px;border-bottom:1px solid #e2e8f0;color:#0b1d36;font-size:15px;font-weight:700;background:{bg};vertical-align:top;">
                {html.escape(str(value))}
              </td>
            </tr>
            """
        )
    model = html.escape(planning.model_description or "—")
    machine_id = html.escape(machine.machine_id)
    work_order = html.escape(planning.work_order or "—")
    brand = html.escape(planning.company or "—")
    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;padding:0;background:#eef2f6;font-family:'Segoe UI',Arial,sans-serif;color:#142033;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#eef2f6;padding:24px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="640" cellspacing="0" cellpadding="0" style="max-width:640px;width:100%;background:#ffffff;border-radius:18px;overflow:hidden;box-shadow:0 12px 36px rgba(11,29,54,.12);">
          <tr>
            <td style="background:linear-gradient(135deg,#0b1d36 0%,#132844 70%,#1c3b63 100%);padding:22px 24px;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td style="vertical-align:middle;">
                    <div style="display:inline-block;background:#e10600;color:#ffffff;font-weight:800;font-size:14px;letter-spacing:.08em;padding:8px 12px;border-radius:10px;">IR</div>
                  </td>
                  <td style="text-align:right;color:#d7e2ef;vertical-align:middle;">
                    <div style="font-size:11px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:#9eb6d0;">Ingersoll Rand</div>
                    <div style="font-size:18px;font-weight:800;color:#ffffff;margin-top:2px;">Production ROTARY</div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="height:5px;background:#e10600;font-size:0;line-height:0;">&nbsp;</td>
          </tr>
          <tr>
            <td style="padding:24px 24px 8px 24px;">
              <div style="display:inline-block;background:#ecfdf5;color:#047857;border:1px solid #a7f3d0;border-radius:999px;padding:6px 12px;font-size:12px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;">
                QC completed
              </div>
              <h1 style="margin:14px 0 8px 0;font-size:26px;line-height:1.2;color:#0b1d36;letter-spacing:-.02em;">
                {machine_id} released
              </h1>
              <p style="margin:0 0 8px 0;color:#475569;font-size:15px;line-height:1.5;">
                Quality Control is complete. This machine is released for dispatch.
              </p>
              <p style="margin:0;color:#0b1d36;font-size:14px;font-weight:700;">
                {brand} · Work order {work_order}
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:8px 24px 6px 24px;">
              <div style="background:#fff7f7;border:1px solid #fecaca;border-left:5px solid #e10600;border-radius:12px;padding:12px 14px;">
                <div style="font-size:11px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:#b10500;margin-bottom:4px;">Model</div>
                <div style="font-size:15px;font-weight:700;color:#0b1d36;line-height:1.35;">{model}</div>
              </div>
            </td>
          </tr>
          <tr>
            <td style="padding:14px 24px 8px 24px;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border:1px solid #e2e8f0;border-radius:14px;overflow:hidden;">
                <tr>
                  <td colspan="2" style="background:#0b1d36;color:#ffffff;padding:12px 14px;font-size:13px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;">
                    Machine details
                  </td>
                </tr>
                {''.join(rows)}
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:10px 24px 24px 24px;">
              <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:12px;padding:14px 16px;color:#1d4ed8;font-size:14px;font-weight:700;">
                Full job card PDF is attached to this email.
              </div>
            </td>
          </tr>
          <tr>
            <td style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:16px 24px;color:#64748b;font-size:12px;line-height:1.5;">
              <strong style="color:#0b1d36;">Ingersoll Rand · Production ROTARY</strong><br>
              One machine · one record · full traceability<br>
              Sent automatically after QC approval · {html.escape(settings.EMAIL_HOST_USER)}
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def send_completion_email(machine):
    if not completion_mail_enabled():
        logger.info("Completion email skipped for %s (disabled or no recipient).", machine.machine_id)
        return False
    recipients = completion_recipients()
    if not recipients:
        logger.info("Completion email skipped for %s (no recipients).", machine.machine_id)
        return False
    if not getattr(settings, "EMAIL_HOST_PASSWORD", ""):
        logger.warning(
            "Completion email for %s not sent: EMAIL_HOST_PASSWORD is not configured.",
            machine.machine_id,
        )
        return False
    try:
        pdf_bytes = build_job_card_pdf(machine)
        planning = machine.planning
        subject = (
            f"QC complete · {machine.machine_id} · "
            f"{planning.work_order or 'WO'} · {planning.model_description or planning.machine_type or 'machine'}"
        )
        message = EmailMultiAlternatives(
            subject=subject,
            body=_mail_body_text(machine),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=recipients,
        )
        message.attach_alternative(_mail_body_html(machine), "text/html")
        message.attach(f"{machine.machine_id}-job-card.pdf", pdf_bytes, "application/pdf")
        sent = message.send(fail_silently=False)
        logger.info("Completion email for %s sent to %s (%s).", machine.machine_id, ", ".join(recipients), sent)
        return bool(sent)
    except Exception:
        logger.exception("Completion email failed for %s", machine.machine_id)
        return False


def queue_completion_email(machine):
    """Send after the DB commit so QC approval never rolls back on mail failure."""
    machine_id = machine.pk

    def _send():
        from machines.models import Machine

        fresh = (
            Machine.objects.select_related("planning", "qc_approved_by", "created_by", "station")
            .prefetch_related("phase_states__phase", "phase_states__started_by", "phase_states__completed_by")
            .filter(pk=machine_id)
            .first()
        )
        if fresh is None:
            return
        send_completion_email(fresh)

    transaction.on_commit(_send)
