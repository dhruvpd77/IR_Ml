"""Active job cards. Assembly and testing follow JOB CARD.xlsx. Electrical follows the Gujarati checklist. End of line follows the rotary defect list."""

from jobcards.official import OFFICIAL

DEFAULT_TEMPLATES = {
    phase: {"name": spec["name"], "description": spec["description"], "fields": spec["fields"]}
    for phase, spec in OFFICIAL.items()
}

DEFAULT_TEMPLATES["QC"] = {
    "name": "Final release",
    "description": "Approve the machine or send it back. The job card itself is the assembly, testing, and end-of-line record.",
    "fields": [
        ("qc_photo", "Inspection photos", "Inspection photos", "image", False, "", ""),
        ("qc_notes", "Release", "Quality notes", "long_text", False, "", ""),
    ],
}

TEMPLATE_MARKERS = {
    "ASSEMBLY": "main_motor_part",
    "TESTING": "test_result",
    "EOL": "eol_1_ok",
    "ELECTRICAL": "elec_1_ok",
    "QC": "qc_photo",
}
