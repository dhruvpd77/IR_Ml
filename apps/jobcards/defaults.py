"""Shared job cards (Electrical / EOL / QC). Assembly and Testing are model-wise via import_model_job_cards."""

from jobcards.official import OFFICIAL

# Runtime shared templates only — Assembly/Testing come from checklist sheets.
SHARED_PHASES = ("ELECTRICAL", "EOL", "QC")

DEFAULT_TEMPLATES = {
    phase: {"name": OFFICIAL[phase]["name"], "description": OFFICIAL[phase]["description"], "fields": OFFICIAL[phase]["fields"]}
    for phase in ("ELECTRICAL", "EOL")
}

DEFAULT_TEMPLATES["QC"] = {
    "name": "Final release",
    "description": "Approve the machine or send it back. The job card itself is the assembly, testing, and end-of-line record.",
    "fields": [
        ("qc_photo", "Inspection photos", "Inspection photos", "image", False, "", ""),
        ("qc_notes", "Release", "Quality notes", "long_text", False, "", ""),
    ],
}

# Legacy unscoped Assembly/Testing field packs (demos/tests copy these onto a checklist_key).
LEGACY_PHASE_TEMPLATES = {
    phase: {"name": OFFICIAL[phase]["name"], "description": OFFICIAL[phase]["description"], "fields": OFFICIAL[phase]["fields"]}
    for phase in ("ASSEMBLY", "TESTING")
}

TEMPLATE_MARKERS = {
    "ASSEMBLY": "main_motor_part",
    "TESTING": "test_result",
    "EOL": "eol_1_ok",
    "ELECTRICAL": "elec_1_ok",
    "QC": "qc_photo",
}
