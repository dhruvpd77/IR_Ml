"""Job card fields taken from JOB CARD.xlsx. Nothing here is invented."""


def _yes(number, section, label):
    prefix = {
        "Assembly checklist": "asm",
        "Before testing": "bef",
        "During testing": "dur",
        "After testing": "aft",
        "General check": "gen",
    }.get(section, "q")
    shown = label if isinstance(number, str) and not str(number)[:1].isdigit() else f"{number}. {label}"
    return (f"{prefix}_{number}", section, shown, "yes_no", False, "", "")


def _text(key, section, label, unit=""):
    return (key, section, label, "short_text", False, unit, "")


def _number(key, section, label, unit=""):
    return (key, section, label, "decimal", False, unit, "")


ASSEMBLY_FIELDS = [
    _text("main_motor_part", "Assembly parts", "Main motor part number"),
    _text("main_motor_serial", "Assembly parts", "Main motor serial number IE2/IE3"),
    _text("fan_motor_part", "Assembly parts", "Fan motor part number"),
    _text("fan_motor_serial", "Assembly parts", "Fan motor serial number"),
    _text("module_part", "Assembly parts", "Module part number"),
    _text("airend_serial", "Assembly parts", "Airend / module serial number"),
    _text("panel_part", "Assembly parts", "Electrical panel part number"),
    _text("panel_serial", "Assembly parts", "Electrical panel serial number"),
    _text("intercooler_part", "Assembly parts", "Inter cooler part number"),
    _text("air_cooler_valve", "Assembly parts", "Air cooler safety valve CCN / serial"),
    _text("aftercooler_part", "Assembly parts", "After cooler part number"),
    _text("oil_cooler_valve", "Assembly parts", "Oil cooler safety valve CCN / serial"),
    _text("oil_cooler_part", "Assembly parts", "Oil cooler part number"),
    _text("ae_safety_valve", "Assembly parts", "A/E safety valve CCN / serial"),
    _text("coupling_gap_note", "Assembly parts", "Linear gap in A/E-motor coupling"),
    _text("helix_serial", "Assembly parts", "Helix serial number"),
    _text("controller_serial", "Assembly parts", "Controller serial number"),
    _yes(1, "Assembly checklist", "સ્કીડ કે મોટર સપોર્ટ માં કોઈ પણ પ્રકાર ની ખામી (સ્ક્રેચ કે ડેમેજ) ?"),
    _yes(2, "Assembly checklist", "મેઈન મોટર, ફેન મોટર માં કોઈ ખામી (પેઇન્ટ કે ડેમેજ) ?"),
    _yes(3, "Assembly checklist", "મેઈન મોટર કે ફેન મોટર CCN પ્રમાણે લગાવેલ છે ?"),
    _yes(4, "Assembly checklist", "એર એન્ડ મોડ્યૂલ માં કોઈ ખામી ?"),
    _yes("5a", "Assembly checklist", "એરએન્ડ વેન્ટ હોલમાંથી બધા પ્લાસ્ટિક પ્લગ્સ કાઢી નાખવામાં આવ્યા છે કે નહીં?"),
    _yes("5b", "Assembly checklist", "ઓઇલ પાઇપ, હોસ, ટ્યૂબ ના કોઈ પાર્ટ્સ માં કોઈ પણ પ્રકાર ની ખામી ?"),
    _yes(6, "Assembly checklist", "કુલર, એસેમ્બલી ના કવર માં કોઈ ખામી ?"),
    _yes(7, "Assembly checklist", "ટ્યૂબ બોલ્ટ કે એલ્બો પર ટૉર્ક માર્કિંગ છે ?"),
    _yes(8, "Assembly checklist", "ફેન મોટર એસેમ્બલીમાં ફ્રી રોટેશન છે?"),
    _yes(9, "Assembly checklist", "મોટર માઉન્ટ અને એર એન્ડ માઉન્ટ ખામી મુક્ત છે ?"),
    _yes(10, "Assembly checklist", "ડોર લોક બરાબર છે ?"),
    _yes(11, "Assembly checklist", "દરેક ડીકેલ અને ઇલેક્ટ્રિક વાયરીંગ એસેમ્બલી બુક પ્રમાણે કરેલ છે ?"),
    _yes(12, "Assembly checklist", "કેબલ પાર્ટ માં કોઈ ખામી ?"),
    _yes(13, "Assembly checklist", "ઇલેક્ટ્રિક કંટ્રોલ પેનલ (ઇન્ટર પાર્ટ) માં કોઈ ખામી ?"),
    _yes(14, "Assembly checklist", "પ્રોપર કેબલ અને ટ્યુબીંગ રાઉટીંગ કરેલ છે ?"),
    _yes(15, "Assembly checklist", "ટોપ ફેબ પાર્ટ માં કોઈ ખામી ?"),
    _yes(16, "Assembly checklist", "ફેબ પાર્ટ માં શેડ વેરિએશન છે ?"),
    _number("q17", "Assembly checklist", "17. પેકેજ એસેમ્બલી દરમ્યાન એરેન્ડ માં ઓઈલ નાખેલ છે ? લિટર", "LTR"),
    _yes(18, "Assembly checklist", "કેનોપી પાર્ટ માં કોઈ અનઇચ્છનીય ગેપ છે ?"),
    _yes(19, "Assembly checklist", "એરએન્ડ–મોટર એસેમ્બલી કરતી વખતે ડોવેલિંગનું કામ ચેક કરીને કન્ફર્મ કરો."),
    _number("q20", "Assembly checklist", "20. કપલિંગ ગેપ", "mm"),
    _text("sub_assembled_by", "Assembly sign off", "Sub assembled by"),
    ("sub_assembled_date", "Assembly sign off", "Sub assembled date", "date", False, "", ""),
    _text("assembled_by", "Assembly sign off", "Assembled by"),
    ("assembled_date", "Assembly sign off", "Assembled date", "date", False, "", ""),
]

_BEFORE = "Before testing"
_DURING = "During testing"
_AFTER = "After testing"

TESTING_FIELDS = [
    _yes(1, _BEFORE, "જરૂરિયાત મુજબ તેલ ભરવા માં આવેલ છે ?"),
    _yes(2, _BEFORE, "કંટ્રોલર માં ડેટા નાખેલ છે ?"),
    _yes(3, _BEFORE, "મેઈન મોટર અને બ્લોઅર મોટર, ફેન મોટર નું રોટેશન ચેક કરવું."),
    _yes(4, _BEFORE, "મશીન પહેલી વખત માં સ્ટાર્ટ થાય છે કે નહીં."),
    _yes(5, _BEFORE, "મેઈન મોટર ઓલર સેટિંગ સેટ કરીને રેટિંગ લખવું"),
    _text("main_motor_olr", _BEFORE, "Main motor OLR"),
    _text("ct_ratio", _BEFORE, "CT ratio"),
    _yes(6, _BEFORE, "ફેન મોટર ઓલર સેટિંગ સેટ કરીને રેટિંગ લખવું"),
    _text("fan_motor_olr", _BEFORE, "Fan motor OLR"),
    _yes(7, _BEFORE, "ઓઇલ પંપ ઓલર સેટિંગ સેટ કરીને રેટિંગ લખવું"),
    _text("oil_pump_olr", _BEFORE, "Oil pump OLR"),
    _yes(8, _DURING, "કોઈ પણ લીકેજ કુલર, હોસ, ટ્યૂબ ફિટિંગ માં જોવા મળેલ છે ?"),
    _yes(9, _DURING, "મશીન રનિંગ કન્ડિશન માં કોઈ અવાજ કરે છે ?"),
    _yes(10, _DURING, "મશીન લોડિંગ, અનલોડીંગ માં બરાબર કામ કરે છે ?"),
    _yes(11, _DURING, "વાલ્વ અને પ્રેશર સ્વિચ બરાબર કામ કરે છે ?"),
    _yes(12, _DURING, "ઓઇલ ટ્રીપ ચેક અને ઈમરજન્સી સ્વિચ બરાબર કામ કરે છે ?"),
    _yes(13, _DURING, "ઓઇલ કેરીઓવર થઇ રહ્યું છે ?"),
    _yes(14, _DURING, "DANFOSS ડ્રાઈવ (ઇનબિલ્ટ અને સ્ટેન્ડ અલોન)"),
    _yes(15, _DURING, "મશીન ને રેટેડ ફૂલ પ્રેશર અને મીનીમમ RPM ચેક કરવું"),
    _yes(16, _DURING, "મશીન માં ઈમરજન્સી સ્ટોપ ચેક કરેલ છે ?"),
    _number("controller_pressure", _DURING, "17. કોન્ટ્રોલર ડિસ્ચાર્જ પ્રેસર રીડિંગ"),
    _number("gauge_pressure", _DURING, "18. ડિસ્ચાર્જ ગેજ નું ડિસ્ચાર્જ પ્રેસર રીડિંગ"),
    _yes(19, _DURING, '"HAND ON" બટન થોડો સમય દબાવી ચેક કરતા "DISABLED" દર્શાવું જોઈએ.'),
    _yes(20, _DURING, 'SUMP PT વાલ્વ કેબલ નીકળી DANFOSS HMI ફરીથી ચાલુ કરતા "CHECK MOTOR ROTATION" ની એરર આવવી જોઈએ.'),
    _number("bearing_oil_pressure", _DURING, "21. બેરિંગ ઓઈલ પ્રેશર"),
    _number("bearing_oil_temp", _DURING, "21. બેરિંગ ઓઈલ ટેમ્પરેચર", "°C"),
    _yes(22, _DURING, "નો-લોડ સ્થિતિમાં ઇનલેટ વેક્યૂમ 9–12.5 psi વચ્ચે સ્થિર થાય છે"),
    _yes(21, _AFTER, "મશીન નો SERIAL NUMBER બરાબર છે ?"),
    _yes(22, _AFTER, "મેઈન મોટર ના રીડીંગ લીધા બાદ ફેન મોટર કે બ્લોઅર ના રોટેશન ચેક કરવું"),
    _yes(23, _AFTER, "મશીન ની CFM વૅલ્યુ રેટેડ છે."),
    _yes(24, _AFTER, "મશીન પાવર રેટેડ છે."),
    _yes(25, _AFTER, "શિપિંગ સ્કોપ ના પાર્ટ્સ મુકેલ છે ?"),
    _yes(26, _AFTER, "શિપિંગ બ્રેકેટ બરાબર ટાઈટ કરેલ છે ?"),
    _yes(27, _AFTER, "પોરો કીટ લગાવેલ તો ચેક કરવી."),
    _yes(28, _AFTER, "NIRVANA વેન્ટને એસેમ્બલી સમયે એરેન્ડમાંથી કાઢી નાખવી."),
    _yes(29, _AFTER, "બ્રાન્ડ મુજબ નેમ પ્લેટની નજીક ટેસ્ટિંગ ઓકે સ્ટીકર ચોંટાડો"),
    _yes(30, _AFTER, "હેલિક્સ ઇન્ટીગ્રેશન થયું કે ન થયું"),
    _yes(31, _AFTER, "Main VFD Program પૂર્ણ થયેલ છે કે નહિં"),
    _yes(32, _AFTER, "Fan VFD Program પૂર્ણ થયેલ છે કે નહિં"),
    _yes(33, _AFTER, "સ્ટાન્ડર્ડ વર્ક મુજબ યોગ્ય સ્થળે નેમ પ્લેટ ઇન્સ્ટોલ કરો"),
    _number("runout_axial", _AFTER, "34. SIERRA coupling run-out axial"),
    _number("runout_radial", _AFTER, "34. SIERRA coupling run-out radial"),
    _number("runout_angular", _AFTER, "34. SIERRA coupling run-out angular"),
    _text("tested_by", "Testing sign off", "Tested by"),
    ("tested_date", "Testing sign off", "Date", "date", False, "", ""),
    ("test_result", "Testing result", "Testing result", "radio", True, "", "OK|NOT OK"),
    ("test_problem", "If not OK", "If not OK, report the problem", "long_text", False, "", ""),
    _yes("earth", "General check", "Earth checked"),
    _yes("temp_trip", "General check", "Temp. trip checked"),
    _yes("amp_trip", "General check", "Amp trip checked"),
    _yes("moisture", "General check", "Moisture checked"),
    _number("vib_load_1", "General check", "Vibration load 1", "mm/s"),
    _number("vib_load_2", "General check", "Vibration load 2", "mm/s"),
    _number("vib_unload_1", "General check", "Vibration unload 1", "mm/s"),
    _number("vib_unload_2", "General check", "Vibration unload 2", "mm/s"),
    _number("vib_axial", "General check", "Airend vibration axial", "mm/s"),
    _number("vib_vertical", "General check", "Airend vibration vertical", "mm/s"),
    _number("vib_horizontal", "General check", "Airend vibration horizontal", "mm/s"),
    _number("oil_fill_1", "General check", "Oil fill 1st", "LTR"),
    _number("oil_fill_2", "General check", "Oil fill 2nd", "LTR"),
    _number("oil_fill_3", "General check", "Oil fill 3rd", "LTR"),
    _number("oil_fill_total", "General check", "Oil fill total", "LTR"),
]

def _elec(number, section, label):
    shown = f"{number}. {label}"
    return [
        (f"elec_{number}_ok", section, shown, "radio", False, "", "OK|NOT OK"),
        (f"elec_{number}_value", section, f"{number}. મૂલ્ય / નોંધ", "short_text", False, "", ""),
        (f"elec_{number}_remark", section, f"{number}. Remark", "short_text", False, "", ""),
    ]


def _elec_section(section, rows):
    fields = []
    for number, label in rows:
        fields.extend(_elec(number, section, label))
    return fields


ELECTRICAL_FIELDS = [
    *_elec_section(
        "Earthing",
        [
            (1, "મશીન બોડી અર્થિંગ કરવામાં આવેલ છે"),
            (2, "પેનલ અર્થિંગ આપવામાં આવેલ છે"),
            (3, "મોટર બોડી અર્થિંગ કનેક્ટ કરેલ છે"),
        ],
    ),
    *_elec_section(
        "મોટર કેબલ",
        [
            (4, "યોગ્ય લગ્સ અને ક્રિમ્પિંગ કરેલ છે"),
            (5, "ફેઝ ઓળખ સ્લીવ્સ આપેલ છે"),
            (6, "ગ્લેન્ડ ટાઇટ અને ક્લેમ્પિંગ કરેલ છે"),
            (7, "ઇન્સ્યુલેશન સ્થિતિ સારી છે"),
        ],
    ),
    *_elec_section(
        "VFD",
        [
            (8, "મોટર kW (નેમપ્લેટ મુજબ)"),
            (9, "લગાવેલ VFD kW"),
            (10, "VFD રેટિંગ મોટર કરતાં સમાન / વધારે છે"),
            (11, "વોલ્ટેજ અને કરંટ રેટિંગ ચેક કરેલ છે"),
            (12, "VFD બોડી અર્થિંગ આપેલ છે"),
        ],
    ),
    *_elec_section(
        "વાયરિંગ",
        [
            (13, "વાયરિંગ ઇલેક્ટ્રિકલ ડ્રોઇંગ મુજબ"),
            (14, "પાવર અને કંટ્રોલ કેબલ અલગ રાખેલ છે"),
            (15, "PVC ચેનલ / ટ્રે ઉપયોગ કરેલ છે"),
            (16, "કોઈ તીખા વળાંક / સ્ટ્રેસ નથી"),
            (17, "કેબલ ફેર્યુલિંગ અને ટેગિંગ કરેલ છે"),
        ],
    ),
    *_elec_section(
        "ES",
        [
            (18, "ઇલેક્ટ્રિકલ ડ્રોઇંગ નંબર"),
            (19, "રિવિઝન નંબર"),
            (20, "લેટેસ્ટ ડ્રોઇંગ અનુસરેલ છે"),
        ],
    ),
    *_elec_section(
        "Critical Sensor",
        [
            (21, "યોગ્ય સેન્સર યોગ્ય ટર્મિનલ પર છે"),
            (22, "વાયરિંગ ઇલેક્ટ્રિકલ ડ્રોઇંગ મુજબ"),
            (23, "શીલ્ડેડ કેબલ ઉપયોગ કરેલ છે"),
            (24, "શીલ્ડ અર્થિંગ એક જ બાજુ કરેલ છે"),
            (25, "ટેસ્ટિંગ દરમ્યાન સિગ્નલ સ્ટેબલ છે"),
        ],
    ),
    *_elec_section(
        "Star - Delta",
        [
            (26, "કોન્ટેક્ટર અને OLR રેટિંગ યોગ્ય છે"),
            (27, "ટાઈમર સેટિંગ ચેક કરેલ છે"),
            (28, "ઇન્ટરલોક યોગ્ય રીતે કામ કરે છે"),
            (29, "ફેઝ સિક્વન્સ યોગ્ય છે"),
        ],
    ),
    *_elec_section(
        "Busbar",
        [
            (30, "ટેસ્ટિંગ પછી બસબાર બોલ્ટ ટાઇટ કરેલ છે"),
        ],
    ),
    ("elec_checked_by", "Electrical sign off", "Checked by", "short_text", False, "", ""),
]

def _eol(number, label):
    return (f"eol_{number}_ok", "Rotary defect list", f"{number}. {label}", "radio", False, "", "OK|NOT OK")


EOL_FIELDS = [
    _eol(1, "Air end shaft not rotating"),
    _eol(2, "Damaged heat exchanger fins"),
    _eol(3, "Dirtiness of complete unit and sub-assembly"),
    _eol(4, "Grommet/cap missing"),
    _eol(5, "Incomplete assembly & test checklist"),
    _eol(6, "Loose assembly"),
    _eol(7, "Missing manual / pen drive / test report / keys"),
    _eol(8, "Missing parts / assembly"),
    _eol(9, "Missing torque marking"),
    _eol(10, "Missing / wrong decals / ES"),
    _eol(11, "Missing / wrong shipping scope items"),
    _eol(12, "Oil leakage"),
    _eol(13, "Wrong assembly / parts fitment"),
    _eol(14, "Wrong branding of accessories installed"),
    _eol(15, "Wrong data in name plate"),
    _eol(16, "Non-standard method of assembly"),
    _eol(17, "Low oil level if oil is not filled up as per BOM"),
    _eol(18, "Tubing routing not as per W/P/AAG/assembly instruction"),
    _text("eol_checked_by", "End of line", "Checked by"),
    ("eol_date", "End of line", "Date", "date", False, "", ""),
]

OFFICIAL = {
    "ASSEMBLY": {
        "name": "Assembly job card",
        "description": "OIL FREE IRN-SEEIRA-DX assembly card from the shop job card.",
        "marker": "main_motor_part",
        "fields": ASSEMBLY_FIELDS,
    },
    "TESTING": {
        "name": "Testing job card",
        "description": "Testing checklist from the shop job card.",
        "marker": "test_result",
        "fields": TESTING_FIELDS,
    },
    "EOL": {
        "name": "Rotary end of line",
        "description": "Rotary defect list. Mark each observation OK or NOT OK.",
        "marker": "eol_1_ok",
        "fields": EOL_FIELDS,
    },
    "ELECTRICAL": {
        "name": "Electrical checklist",
        "description": "Gujarati electrical checklist. Each point has a value, OK or NOT OK, and a remark.",
        "marker": "elec_1_ok",
        "fields": ELECTRICAL_FIELDS,
    },
}
