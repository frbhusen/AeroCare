"""Server-side structure + range validation for ophthalmology exams.

Nested schemas are dicts of core validation fields (or nested dicts). Unknown keys are dropped
(never stored); errors are reported with dotted paths, e.g. {"right_eye.iop.value": "must be <= 80"}.
"""
import re
from decimal import Decimal

from backend.app.core.errors import ValidationError
from backend.app.core.validation import Bool, Enum, Field, Int, Num, Str

IOP_METHODS = ("goldmann", "non_contact", "tonopen", "icare", "perkins", "palpation", "other")
PUPIL_REACTIONS = ("brisk", "sluggish", "non_reactive")
RAPD = ("absent", "present")
MOTILITY = ("full", "restricted")
LENS_TYPES = ("single_vision", "bifocal", "progressive", "reading", "contact_lens", "other")

_SNELLEN = re.compile(r"\d{1,2}(\.\d)?/\d{1,4}(\.\d{1,2})?([+-]\d)?")
_DECIMAL = re.compile(r"\d(\.\d{1,3})?")
_LOW_VISION = re.compile(r"(CF|HM|LP|PL|NLP|NPL)( [A-Z0-9. ]{1,15})?")


class VisualAcuity(Field):
    """Snellen fraction (6/9, 20/40, 6/12+2), decimal 0.0-2.0, or CF/HM/LP/NLP (+ short qualifier)."""

    def convert(self, v):
        s = re.sub(r"\s+", " ", str(v).strip().upper())
        if _SNELLEN.fullmatch(s):
            num, den = s.split("/")
            den = re.split(r"[+-]", den)[0]
            if float(num) <= 0 or float(den) <= 0:
                raise ValueError("must be a valid Snellen fraction")
            return s
        if _DECIMAL.fullmatch(s):
            if float(s) > 2.0:
                raise ValueError("decimal acuity must be between 0 and 2.0")
            return s
        if _LOW_VISION.fullmatch(s):
            return s
        raise ValueError("must be Snellen (e.g. 6/9, 20/40), decimal (0-2.0) or CF/HM/LP/NLP")


def _txt(n=1000):
    return Str(max_len=n)


REFRACTION = {
    "sphere": Num(min_value=-30, max_value=30, places=2),
    "cylinder": Num(min_value=-15, max_value=15, places=2),
    "axis": Int(min_value=0, max_value=180),
    "add": Num(min_value=0, max_value=5, places=2),
}

EYE = {
    "visual_acuity": {"uncorrected": VisualAcuity(), "best_corrected": VisualAcuity(), "pinhole": VisualAcuity(),
                      "near": Str(max_len=20)},
    "refraction": REFRACTION,
    "iop": {"value": Num(min_value=0, max_value=80, places=1), "method": Enum(IOP_METHODS)},
    "pupils": {"size_mm": Num(min_value=0, max_value=12, places=1), "shape": _txt(100),
               "reaction": Enum(PUPIL_REACTIONS), "rapd": Enum(RAPD)},
    "motility": {"status": Enum(MOTILITY), "notes": _txt()},
    "slit_lamp": {k: _txt() for k in ("lids", "conjunctiva", "cornea", "anterior_chamber", "iris", "lens")},
    "fundus": {"dilated": Bool(), "optic_disc": _txt(), "cup_disc_ratio": Num(min_value=0, max_value=1, places=2),
               "macula": _txt(), "vessels": _txt(), "periphery": _txt()},
    "notes": _txt(2000),
}

GLASSES = {
    "right": REFRACTION,
    "left": REFRACTION,
    "pd_mm": Num(min_value=40, max_value=80, places=1),
    "lens_type": Enum(LENS_TYPES),
    "notes": _txt(2000),
}


def _clean(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() and v.as_tuple().exponent >= 0 else float(v)
    return v


def _walk(value, schema, path, errors):
    if not isinstance(value, dict):
        errors[path] = "must be an object"
        return None
    out = {}
    for key, field in schema.items():
        if key not in value:
            continue
        sub = f"{path}.{key}"
        if isinstance(field, dict):
            if value[key] is None:
                continue
            res = _walk(value[key], field, sub, errors)
            if res:
                out[key] = res
            continue
        try:
            res = field.run(value[key])
        except ValueError as e:
            errors[sub] = str(e)
            continue
        if res is not None:
            out[key] = _clean(res)
    return out


def _axis_rule(refr, path, errors):
    if refr and refr.get("cylinder") not in (None, 0) and refr.get("axis") is None:
        errors[f"{path}.axis"] = "is required when cylinder is set"


def validate_block(value, kind, path):
    """kind: 'eye' | 'glasses'. Returns the cleaned dict (unknown keys dropped) or raises 422."""
    if value is None:
        return {}
    errors = {}
    out = _walk(value, EYE if kind == "eye" else GLASSES, path, errors) or {}
    if kind == "eye":
        _axis_rule(out.get("refraction"), f"{path}.refraction", errors)
    else:
        _axis_rule(out.get("right"), f"{path}.right", errors)
        _axis_rule(out.get("left"), f"{path}.left", errors)
    if errors:
        raise ValidationError("Invalid input", details=errors)
    return out


def describe(schema=None):
    """Field catalog for the UI meta endpoint."""
    schema = EYE if schema is None else schema
    out = {}
    for k, f in schema.items():
        if isinstance(f, dict):
            out[k] = describe(f)
        elif isinstance(f, Enum):
            out[k] = {"type": "enum", "choices": f.choices}
        elif isinstance(f, (Num, Int)):
            out[k] = {"type": "number", "min": _clean(Decimal(str(f.min_value))) if f.min_value is not None else None,
                      "max": _clean(Decimal(str(f.max_value))) if f.max_value is not None else None,
                      "step": (10 ** -f.places) if isinstance(f, Num) and f.places else 1}
        elif isinstance(f, VisualAcuity):
            out[k] = {"type": "visual_acuity"}
        elif isinstance(f, Bool):
            out[k] = {"type": "boolean"}
        else:
            out[k] = {"type": "text", "max_length": getattr(f, "max_len", None)}
    return out
