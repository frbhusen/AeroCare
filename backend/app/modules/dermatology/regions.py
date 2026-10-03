"""Shared body-region catalog (data in code; stable codes).

Used by Dermatology (affected areas) and Laser Hair Removal (treatment areas). Each region has
bilingual labels, the body views it can be selected on (front/back), a group for list/legend
rendering, and an `order` for stable display. Left/right are the PATIENT's left/right.
The same codes are meant to be used as mesh/zone ids by an interactive 3D body and as
element ids in a 2D SVG fallback, so codes must never be renamed (add new ones instead).
"""

GROUPS = [
    {"code": "head_neck", "en": "Head & neck", "ar": "الرأس والرقبة"},
    {"code": "upper_limbs", "en": "Arms & hands", "ar": "الذراعان واليدان"},
    {"code": "trunk", "en": "Trunk", "ar": "الجذع"},
    {"code": "intimate", "en": "Bikini & buttocks", "ar": "منطقة البكيني والأرداف"},
    {"code": "lower_limbs", "en": "Legs & feet", "ar": "الساقان والقدمان"},
]

F, B, FB = ("front",), ("back",), ("front", "back")

# (code, en, ar, views, group, mirror_of)
_REGIONS = [
    ("scalp", "Scalp", "فروة الرأس", FB, "head_neck", None),
    ("face", "Full face", "الوجه كاملاً", F, "head_neck", None),
    ("forehead", "Forehead", "الجبهة", F, "head_neck", None),
    ("upper_lip", "Upper lip", "الشفة العليا", F, "head_neck", None),
    ("chin", "Chin", "الذقن", F, "head_neck", None),
    ("cheeks", "Cheeks", "الخدان", F, "head_neck", None),
    ("neck", "Neck", "الرقبة", FB, "head_neck", None),
    ("shoulders", "Shoulders", "الكتفان", FB, "upper_limbs", None),
    ("underarm_left", "Left underarm", "الإبط الأيسر", F, "upper_limbs", "underarm_right"),
    ("underarm_right", "Right underarm", "الإبط الأيمن", F, "upper_limbs", "underarm_left"),
    ("upper_arm_left", "Left upper arm", "العضد الأيسر", FB, "upper_limbs", "upper_arm_right"),
    ("upper_arm_right", "Right upper arm", "العضد الأيمن", FB, "upper_limbs", "upper_arm_left"),
    ("forearm_left", "Left forearm", "الساعد الأيسر", FB, "upper_limbs", "forearm_right"),
    ("forearm_right", "Right forearm", "الساعد الأيمن", FB, "upper_limbs", "forearm_left"),
    ("hands", "Hands", "اليدان", FB, "upper_limbs", None),
    ("full_arms", "Full arms", "الذراعان كاملتان", FB, "upper_limbs", None),
    ("chest", "Chest", "الصدر", F, "trunk", None),
    ("abdomen", "Abdomen", "البطن", F, "trunk", None),
    ("upper_back", "Upper back", "أعلى الظهر", B, "trunk", None),
    ("lower_back", "Lower back", "أسفل الظهر", B, "trunk", None),
    ("bikini", "Bikini", "منطقة البكيني", F, "intimate", None),
    ("buttocks", "Buttocks", "الأرداف", B, "intimate", None),
    ("thigh_left", "Left thigh", "الفخذ الأيسر", FB, "lower_limbs", "thigh_right"),
    ("thigh_right", "Right thigh", "الفخذ الأيمن", FB, "lower_limbs", "thigh_left"),
    ("lower_leg_left", "Left lower leg", "الساق اليسرى", FB, "lower_limbs", "lower_leg_right"),
    ("lower_leg_right", "Right lower leg", "الساق اليمنى", FB, "lower_limbs", "lower_leg_left"),
    ("feet", "Feet", "القدمان", FB, "lower_limbs", None),
    ("full_legs", "Full legs", "الساقان كاملتان", FB, "lower_limbs", None),
]

REGIONS = [
    {"code": c, "en": en, "ar": ar, "views": list(views), "group": g, "mirror_of": m, "order": i}
    for i, (c, en, ar, views, g, m) in enumerate(_REGIONS)
]
REGION_BY_CODE = {r["code"]: r for r in REGIONS}
REGION_CODES = tuple(REGION_BY_CODE)
SIDES = ("front", "back")


def catalog():
    return {"groups": GROUPS, "regions": REGIONS, "views": list(SIDES)}


def label(code, lang="en"):
    r = REGION_BY_CODE.get(code)
    return r[lang] if r else code
