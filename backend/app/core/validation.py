"""Small declarative input validation for JSON bodies and query strings.

Usage:
    data = validate(request_json(), {
        "full_name": Str(required=True, max_len=200),
        "dob": Date(),
        "gender": Enum(["male", "female"]),
        "price": Money(min_value=0),
    }, partial=False)

Unknown keys are ignored (never mass-assigned). Errors are collected and raised as one
ValidationError with details {field: message}.
"""
import re
import uuid
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from flask import request

from .errors import ValidationError

_MISSING = object()


class Field:
    def __init__(self, required=False, nullable=True, default=_MISSING):
        self.required = required
        self.nullable = nullable
        self.default = default

    def convert(self, v):  # pragma: no cover - overridden
        return v

    def run(self, v):
        if v is None or (isinstance(v, str) and v.strip() == "" and not isinstance(self, Str)):
            if not self.nullable or self.required:
                raise ValueError("is required")
            return None
        return self.convert(v)


class Str(Field):
    def __init__(self, min_len=0, max_len=255, pattern=None, strip=True, **kw):
        super().__init__(**kw)
        self.min_len, self.max_len, self.strip = min_len, max_len, strip
        self.pattern = re.compile(pattern) if pattern else None

    def run(self, v):
        if v is None:
            if self.required or not self.nullable:
                raise ValueError("is required")
            return None
        if not isinstance(v, (str, int, float)):
            raise ValueError("must be text")
        v = str(v)
        if self.strip:
            v = v.strip()
        if v == "":
            if self.required:
                raise ValueError("is required")
            return None if self.nullable else ""
        if len(v) < self.min_len:
            raise ValueError(f"must be at least {self.min_len} characters")
        if len(v) > self.max_len:
            raise ValueError(f"must be at most {self.max_len} characters")
        if self.pattern and not self.pattern.fullmatch(v):
            raise ValueError("has an invalid format")
        return v


class Text(Str):
    def __init__(self, max_len=20000, **kw):
        super().__init__(max_len=max_len, **kw)


class Int(Field):
    def __init__(self, min_value=None, max_value=None, **kw):
        super().__init__(**kw)
        self.min_value, self.max_value = min_value, max_value

    def convert(self, v):
        if isinstance(v, bool):
            raise ValueError("must be an integer")
        try:
            iv = int(v)
        except (TypeError, ValueError):
            raise ValueError("must be an integer")
        if isinstance(v, float) and v != iv:
            raise ValueError("must be an integer")
        if self.min_value is not None and iv < self.min_value:
            raise ValueError(f"must be >= {self.min_value}")
        if self.max_value is not None and iv > self.max_value:
            raise ValueError(f"must be <= {self.max_value}")
        return iv


class Id(Int):
    def __init__(self, **kw):
        super().__init__(min_value=1, max_value=2**31 - 1, **kw)


class Num(Field):
    """Decimal number (quantities, measurements)."""

    def __init__(self, min_value=None, max_value=None, places=None, **kw):
        super().__init__(**kw)
        self.min_value, self.max_value, self.places = min_value, max_value, places

    def convert(self, v):
        if isinstance(v, bool):
            raise ValueError("must be a number")
        try:
            d = Decimal(str(v))
        except (InvalidOperation, ValueError):
            raise ValueError("must be a number")
        if not d.is_finite():
            raise ValueError("must be a number")
        if self.places is not None:
            if d.as_tuple().exponent < -self.places:
                raise ValueError(f"must have at most {self.places} decimal places")
        if self.min_value is not None and d < Decimal(str(self.min_value)):
            raise ValueError(f"must be >= {self.min_value}")
        if self.max_value is not None and d > Decimal(str(self.max_value)):
            raise ValueError(f"must be <= {self.max_value}")
        return d


class Money(Num):
    def __init__(self, min_value=0, max_value=10**12, **kw):
        super().__init__(min_value=min_value, max_value=max_value, places=2, **kw)


class Bool(Field):
    def convert(self, v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str) and v.lower() in {"true", "1", "yes", "on"}:
            return True
        if isinstance(v, str) and v.lower() in {"false", "0", "no", "off"}:
            return False
        if v in (0, 1):
            return bool(v)
        raise ValueError("must be true or false")


class Enum(Field):
    def __init__(self, choices, **kw):
        super().__init__(**kw)
        self.choices = list(choices)

    def convert(self, v):
        if v not in self.choices:
            raise ValueError("must be one of: " + ", ".join(map(str, self.choices)))
        return v


class Date(Field):
    def convert(self, v):
        if isinstance(v, date) and not isinstance(v, datetime):
            return v
        try:
            return date.fromisoformat(str(v)[:10])
        except ValueError:
            raise ValueError("must be a date (YYYY-MM-DD)")


class DateTime(Field):
    """ISO-8601 datetime. Naive values are interpreted as Asia/Damascus local time."""

    def convert(self, v):
        from .timeutil import TZ
        try:
            dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("must be an ISO datetime")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt


class Time(Field):
    def convert(self, v):
        try:
            return time.fromisoformat(str(v))
        except ValueError:
            raise ValueError("must be a time (HH:MM)")


class Uuid(Field):
    def convert(self, v):
        try:
            return str(uuid.UUID(str(v)))
        except ValueError:
            raise ValueError("must be a UUID")


class List(Field):
    def __init__(self, item: Field, max_items=200, min_items=0, **kw):
        super().__init__(**kw)
        self.item, self.max_items, self.min_items = item, max_items, min_items

    def convert(self, v):
        if not isinstance(v, list):
            raise ValueError("must be a list")
        if len(v) > self.max_items:
            raise ValueError(f"must have at most {self.max_items} items")
        if len(v) < self.min_items:
            raise ValueError(f"must have at least {self.min_items} items")
        out = []
        for i, x in enumerate(v):
            try:
                out.append(self.item.run(x))
            except ValueError as e:
                raise ValueError(f"item {i}: {e}")
            except ValidationError as e:
                raise ValueError(f"item {i}: {e.details}")
        return out


class Obj(Field):
    """Nested object validated against a schema dict."""

    def __init__(self, schema, **kw):
        super().__init__(**kw)
        self.schema = schema

    def convert(self, v):
        if not isinstance(v, dict):
            raise ValueError("must be an object")
        return validate(v, self.schema)


class JsonDict(Field):
    """Free-form JSON object (bounded size); used for extensible specialty fields."""

    def __init__(self, max_keys=100, **kw):
        super().__init__(**kw)
        self.max_keys = max_keys

    def convert(self, v):
        if not isinstance(v, dict):
            raise ValueError("must be an object")
        if len(v) > self.max_keys:
            raise ValueError("too many keys")
        import json
        if len(json.dumps(v)) > 50000:
            raise ValueError("is too large")
        return v


USERNAME_RE = r"[A-Za-z0-9._-]{3,50}"
EMAIL_RE = r"[^@\s]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}"
PHONE_RE = r"[0-9+()\- ]{3,30}"
COLOR_RE = r"#[0-9a-fA-F]{6}"


def validate(data, schema, partial=False):
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object")
    out, errors = {}, {}
    for key, field in schema.items():
        if key not in data:
            if partial:
                continue
            if field.required:
                errors[key] = "is required"
            elif field.default is not _MISSING:
                out[key] = field.default() if callable(field.default) else field.default
            continue
        try:
            out[key] = field.run(data[key])
        except ValueError as e:
            errors[key] = str(e)
    if errors:
        raise ValidationError("Invalid input", details=errors)
    return out


def request_json():
    data = request.get_json(silent=True)
    if data is None and request.data:
        raise ValidationError("Malformed JSON body")
    return data or {}


def query_args(schema):
    return validate({k: v for k, v in request.args.items()}, schema)
