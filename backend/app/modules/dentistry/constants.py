"""Dental vocabularies kept compatible with AeroDent's UI (web/js/state.js, odontogram.js, i18n.js).

Tooth numbering = AeroDent's Universal scheme viewed facing the patient:
  permanent: 1..32  upper arch 1 -> 16, lower arch 32 -> 17 (tooth 32 sits under tooth 1)
  primary:   1..20  displayed as letters A..T; upper 1 -> 10 (A..J), lower 20 -> 11 (T..K)
FDI equivalents are exposed by the meta endpoint for display only.
"""
TOOTH_MODES = ("permanent", "primary")
TOOTH_RANGES = {"permanent": (1, 32), "primary": (1, 20)}

# Chart conditions. The first eight are AeroDent's (legend + action buttons + i18n keys);
# the rest are additive. "clear" is an action (resets the tooth), never stored.
CONDITIONS = ("healthy", "decay", "filling", "amalgam", "crown", "rct", "extract", "implant",
              "missing", "bridge", "veneer", "fracture", "sealant")
CLEAR = "clear"
# AeroDent's quick-action buttons (key, i18n key), in order.
CHART_ACTIONS = ("decay", "filling", "crown", "rct", "extract", "implant", "clear")
SURFACES = ("M", "O", "D", "B", "L")  # mesial, occlusal/incisal, distal, buccal/facial, lingual/palatal

# Suggested procedure names for treatments / plans (free text is still accepted, max 150).
PROCEDURES = ("examination", "cleaning", "scaling", "filling", "amalgam", "crown", "rct", "extract", "implant",
              "bridge", "veneer", "sealant", "whitening", "orthodontics", "denture", "other")

STATUSES = ("planned", "accepted", "scheduled", "in-progress", "completed", "cancelled")
PRIORITIES = ("low", "medium", "high")
XRAY_TYPES = ("periapical", "bitewing", "panoramic", "cephalometric", "occlusal", "cbct", "other")
XRAY_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "image/tiff", "application/dicom"}


def _fdi_permanent(n):
    if n <= 8:
        return 19 - n          # 1..8  -> 18..11
    if n <= 16:
        return 12 + n          # 9..16 -> 21..28
    if n <= 24:
        return 55 - n          # 17..24 -> 38..31
    return 16 + n              # 25..32 -> 41..48


def _fdi_primary(n):
    if n <= 5:
        return 56 - n          # A..E -> 55..51
    if n <= 10:
        return 55 + n          # F..J -> 61..65
    if n <= 15:
        return 86 - n          # K..O -> 75..71
    return 65 + n              # P..T -> 81..85


def tooth_label(mode, n):
    return chr(64 + n) if mode == "primary" else str(n)


def numbering():
    return {
        "scheme": "universal",
        "permanent": {"min": 1, "max": 32, "upper": list(range(1, 17)), "lower": list(range(32, 16, -1)),
                      "labels": {n: str(n) for n in range(1, 33)},
                      "fdi": {n: _fdi_permanent(n) for n in range(1, 33)}},
        "primary": {"min": 1, "max": 20, "upper": list(range(1, 11)), "lower": list(range(20, 10, -1)),
                    "labels": {n: chr(64 + n) for n in range(1, 21)},
                    "fdi": {n: _fdi_primary(n) for n in range(1, 21)}},
    }
