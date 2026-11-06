"""Shared codes for roles, phases, and machine status. No model imports."""


class Roles:
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    PLANNING_DATA_ENTRY = "PLANNING_DATA_ENTRY"
    PLANNER = "PLANNER"
    PRODUCTION_LEADER = "PRODUCTION_LEADER"
    ASSEMBLY = "ASSEMBLY"
    ELECTRICAL = "ELECTRICAL"
    TESTING = "TESTING"
    EOL = "EOL"
    QC = "QC"

    CHOICES = [
        (SUPER_ADMIN, "Super Admin"),
        (ADMIN, "Admin"),
        (PLANNING_DATA_ENTRY, "Planning Data Entry"),
        (PRODUCTION_LEADER, "Serial and station"),
        (ASSEMBLY, "Assembly"),
        (ELECTRICAL, "Electrical"),
        (TESTING, "Testing"),
        (EOL, "EOL"),
        (QC, "Quality Control"),
    ]
    MANAGEMENT = {SUPER_ADMIN, ADMIN}
    PHASE_ROLES = [
        PLANNING_DATA_ENTRY,
        PRODUCTION_LEADER,
        ASSEMBLY,
        ELECTRICAL,
        TESTING,
        EOL,
        QC,
    ]


class PhaseCode:
    PLANNING = "PLANNING"
    PLANNER = "PLANNER"
    PRODUCTION = "PRODUCTION"
    ASSEMBLY = "ASSEMBLY"
    ELECTRICAL = "ELECTRICAL"
    TESTING = "TESTING"
    EOL = "EOL"
    QC = "QC"
    BUILD = "BUILD"

    CHOICES = [
        (PLANNING, "Planning Data Entry"),
        (PLANNER, "Serial assignment"),
        (PRODUCTION, "Production Leader"),
        (ASSEMBLY, "Assembly"),
        (ELECTRICAL, "Electrical"),
        (TESTING, "Testing"),
        (EOL, "End of Line"),
        (QC, "Quality Control"),
    ]
    JOB_CARDS = {ASSEMBLY, ELECTRICAL, TESTING, EOL, QC}
    PARALLEL = {ASSEMBLY, ELECTRICAL}


class PhaseStatus:
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"

    CHOICES = [
        (PENDING, "Pending"),
        (IN_PROGRESS, "In Progress"),
        (COMPLETED, "Completed"),
    ]


class MachineStatus:
    DRAFT = "DRAFT"
    WITH_PLANNER = "WITH_PLANNER"
    WITH_PRODUCTION = "WITH_PRODUCTION"
    IN_PRODUCTION = "IN_PRODUCTION"
    IN_TESTING = "IN_TESTING"
    IN_EOL = "IN_EOL"
    IN_QC = "IN_QC"
    COMPLETED = "COMPLETED"
    UNDER_REWORK = "UNDER_REWORK"

    CHOICES = [
        (DRAFT, "Draft"),
        (WITH_PLANNER, "Planning Submitted"),
        (WITH_PRODUCTION, "With Production Leader"),
        (IN_PRODUCTION, "In Production"),
        (IN_TESTING, "In Testing"),
        (IN_EOL, "In EOL"),
        (IN_QC, "In QC"),
        (COMPLETED, "Completed"),
        (UNDER_REWORK, "Under Rework"),
    ]
    LABELS = dict(CHOICES)


class ShopLine:
    LM1 = "LM1"
    LM2 = "LM2"
    SMALL = "SMALL"

    CHOICES = [
        (LM1, "Large / Medium – Line 1"),
        (LM2, "Large / Medium – Line 2"),
        (SMALL, "Small Line"),
    ]


class StationKind:
    SUB = "SUB"
    ASSEMBLY = "ASSEMBLY"
    FINAL = "FINAL"

    CHOICES = [
        (SUB, "Sub assembly"),
        (ASSEMBLY, "Assembly"),
        (FINAL, "Assembly"),
    ]


TEST_AREAS = ("Test area 1", "Test area 2", "Test area 3")


class Priority:
    FIRST = "1ST"
    SECOND = "2ND"
    STANDARD = "STANDARD"

    CHOICES = [
        (FIRST, "1st Priority"),
        (SECOND, "2nd Priority"),
        (STANDARD, "standard"),
    ]
    LABELS = dict(CHOICES)
    NORMALIZE = {
        "1st priority": FIRST,
        "1st": FIRST,
        "first": FIRST,
        "critical": FIRST,
        "high": FIRST,
        "2nd priority": SECOND,
        "2nd": SECOND,
        "second": SECOND,
        "medium": SECOND,
        "med": SECOND,
        "standard": STANDARD,
        "normal": STANDARD,
        "low": STANDARD,
    }


class EventType:
    CREATED = "CREATED"
    PHASE_STARTED = "PHASE_STARTED"
    PHASE_COMPLETED = "PHASE_COMPLETED"
    SERIAL_ASSIGNED = "SERIAL_ASSIGNED"
    STATION_ASSIGNED = "STATION_ASSIGNED"
    REJECTED = "REJECTED"
    REWORK_COMPLETED = "REWORK_COMPLETED"
    APPROVED = "APPROVED"
    NOTE = "NOTE"
    REVISION = "REVISION"

    CHOICES = [
        (CREATED, "Created"),
        (PHASE_STARTED, "Phase started"),
        (PHASE_COMPLETED, "Phase completed"),
        (SERIAL_ASSIGNED, "Serial assigned"),
        (STATION_ASSIGNED, "Station assigned"),
        (REJECTED, "Rejected"),
        (REWORK_COMPLETED, "Rework completed"),
        (APPROVED, "Approved"),
        (NOTE, "Note"),
        (REVISION, "Job card revision"),
    ]


class FieldType:
    SHORT_TEXT = "short_text"
    LONG_TEXT = "long_text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    DATE = "date"
    TIME = "time"
    DROPDOWN = "dropdown"
    RADIO = "radio"
    YES_NO = "yes_no"
    PASS_FAIL = "pass_fail"
    CHECKBOX = "checkbox"
    MEASUREMENT = "measurement"
    FILE = "file"
    IMAGE = "image"
    VIDEO = "video"
    REMARKS = "remarks"
    SIGNATURE = "signature"

    CHOICES = [
        (SHORT_TEXT, "Short text"),
        (LONG_TEXT, "Long text"),
        (INTEGER, "Integer"),
        (DECIMAL, "Decimal"),
        (DATE, "Date"),
        (TIME, "Time"),
        (DROPDOWN, "Dropdown"),
        (RADIO, "Radio buttons"),
        (YES_NO, "Yes / No"),
        (PASS_FAIL, "Pass / Fail / N/A"),
        (CHECKBOX, "Checkbox"),
        (MEASUREMENT, "Measurement"),
        (FILE, "File upload"),
        (IMAGE, "Image upload"),
        (VIDEO, "Video upload"),
        (REMARKS, "Remarks"),
        (SIGNATURE, "Signature / approval"),
    ]
    FILE_TYPES = {FILE, IMAGE, VIDEO}


# Role that operates each phase. Management can operate every phase.
PHASE_ROLE = {
    PhaseCode.PLANNING: Roles.PLANNING_DATA_ENTRY,
    PhaseCode.PLANNER: Roles.PRODUCTION_LEADER,
    PhaseCode.PRODUCTION: Roles.PRODUCTION_LEADER,
    PhaseCode.ASSEMBLY: Roles.ASSEMBLY,
    PhaseCode.ELECTRICAL: Roles.ELECTRICAL,
    PhaseCode.TESTING: Roles.TESTING,
    PhaseCode.EOL: Roles.EOL,
    PhaseCode.QC: Roles.QC,
}

ROLE_DEPARTMENT = {
    Roles.SUPER_ADMIN: "ADMIN",
    Roles.ADMIN: "ADMIN",
    Roles.PLANNING_DATA_ENTRY: "PLANNING",
    Roles.PLANNER: "PLANNER",
    Roles.PRODUCTION_LEADER: "PRODUCTION",
    Roles.ASSEMBLY: "ASSEMBLY",
    Roles.ELECTRICAL: "ELECTRICAL",
    Roles.TESTING: "TESTING",
    Roles.EOL: "EOL",
    Roles.QC: "QC",
}

DEPARTMENTS = [
    ("ADMIN", "Administration", "System administration"),
    ("PLANNING", "Planning", "Planning data entry"),
    ("PLANNER", "Planning Office", "Serial assignment and planner release"),
    ("PRODUCTION", "Production", "Production leadership and station allocation"),
    ("ASSEMBLY", "Assembly", "Mechanical assembly"),
    ("ELECTRICAL", "Electrical", "Electrical assembly and wiring"),
    ("TESTING", "Testing", "Performance and functional testing"),
    ("EOL", "End of Line", "End-of-line inspection"),
    ("QC", "Quality Control", "Final quality approval"),
]

PHASE_DEFINITIONS = [
    (PhaseCode.PLANNING, "Planning Data Entry", "Initial machine registration", 1, "", "PLANNING"),
    (PhaseCode.PLANNER, "Serial assignment", "Production leader assigns the machine serial", 2, "", "PRODUCTION"),
    (PhaseCode.PRODUCTION, "Production Leader", "Station allocation and production release", 3, "", "PRODUCTION"),
    (PhaseCode.ASSEMBLY, "Assembly", "Mechanical assembly job card", 4, "BUILD", "ASSEMBLY"),
    (PhaseCode.ELECTRICAL, "Electrical", "Electrical job card", 4, "BUILD", "ELECTRICAL"),
    (PhaseCode.TESTING, "Testing", "Performance testing", 5, "", "TESTING"),
    (PhaseCode.EOL, "End of Line", "End-of-line inspection", 6, "", "EOL"),
    (PhaseCode.QC, "Quality Control", "Final inspection and release", 7, "", "QC"),
]

STATUS_FOR_OPENED_PHASE = {
    PhaseCode.PLANNING: MachineStatus.DRAFT,
    PhaseCode.PLANNER: MachineStatus.WITH_PLANNER,
    PhaseCode.PRODUCTION: MachineStatus.WITH_PRODUCTION,
    PhaseCode.ASSEMBLY: MachineStatus.IN_PRODUCTION,
    PhaseCode.ELECTRICAL: MachineStatus.IN_PRODUCTION,
    PhaseCode.TESTING: MachineStatus.IN_TESTING,
    PhaseCode.EOL: MachineStatus.IN_EOL,
    PhaseCode.QC: MachineStatus.IN_QC,
}

PLANNING_COLUMNS = [
    ("company", "Brand", True),
    ("ccn", "CCN", True),
    ("model_description", "Model Description", True),
    ("machine_type", "Type", True),
    ("work_order", "Work Order", False),
    ("calibration", "Calibration", False),
    ("shift", "Shift of machine", False),
    ("test_report_bar", "Test Report Required at Bar", False),
    ("export_packing_required", "Export Packing Required", False),
    ("customer_inspection", "Customer Inspection", False),
    ("priority", "Priority", False),
]
