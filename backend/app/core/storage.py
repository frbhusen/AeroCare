"""Storage backend abstraction + upload content validation.

Backends implement save/open/delete over opaque keys. The default LocalStorage keeps bytes
outside any web root under STORAGE_ROOT/<center>/<yyyy>/<mm>/<random>. Swap in an object-store
backend later by implementing the same three methods and changing get_storage().
"""
import hashlib
import os
import re
import secrets
from pathlib import Path

from flask import current_app

from .errors import ValidationError
from .timeutil import utcnow

KEY_RE = re.compile(r"^\d+/\d{4}/\d{2}/[a-f0-9]{32}$")

# extension -> (mime, sniff function name)
ALLOWED = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp",
    "bmp": "image/bmp", "tif": "image/tiff", "tiff": "image/tiff", "pdf": "application/pdf",
    "doc": "application/msword", "xls": "application/vnd.ms-excel",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "txt": "text/plain", "dcm": "application/dicom",
}
IMAGE_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "image/tiff"}


def _sniff(head: bytes):
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:2] == b"BM":
        return "image/bmp"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "ole"
    if len(head) >= 132 and head[128:132] == b"DICM":
        return "application/dicom"
    return None


def _looks_like_text(data: bytes):
    if b"\x00" in data:
        return False
    try:
        txt = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    low = txt[:4096].lower()
    return not any(t in low for t in ("<script", "<html", "<?php", "#!/"))


def validate_upload(filename: str, data: bytes):
    """Return (safe_display_name, mime). Rejects by extension allow-list AND content sniffing;
    the client-supplied MIME type is ignored."""
    max_bytes = current_app.config["MAX_FILE_BYTES"]
    if not data:
        raise ValidationError("The file is empty.", code="file_empty")
    if len(data) > max_bytes:
        raise ValidationError("Files must be 15 MB or smaller.", code="file_too_large")
    name = os.path.basename((filename or "").replace("\\", "/")).strip() or "file"
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", name)[:200]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED:
        raise ValidationError("This file type is not allowed.", code="file_type_not_allowed")
    expected = ALLOWED[ext]
    sniffed = _sniff(data[:200])
    ok = False
    if expected in IMAGE_MIMES or expected in ("application/pdf", "application/dicom"):
        ok = sniffed == expected or (expected == "image/jpeg" and sniffed == "image/jpeg")
    elif ext in ("docx", "xlsx", "pptx"):
        ok = sniffed == "zip" and _ooxml_ok(data, ext)
    elif ext in ("doc", "xls"):
        ok = sniffed == "ole"
    elif ext == "txt":
        ok = sniffed is None and _looks_like_text(data[:65536])
    if not ok:
        raise ValidationError("The file content does not match its type.", code="file_content_mismatch")
    return name, expected


def _ooxml_ok(data, ext):
    import io
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
    except zipfile.BadZipFile:
        return False
    if "[Content_Types].xml" not in names:
        return False
    if any(n.lower().endswith((".bin",)) and "vbaproject" in n.lower() for n in names):
        return False  # macro-enabled content
    prefix = {"docx": "word/", "xlsx": "xl/", "pptx": "ppt/"}[ext]
    return any(n.startswith(prefix) for n in names)


class LocalStorage:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key):
        if not KEY_RE.match(key or ""):
            raise ValueError("invalid storage key")
        p = (self.root / key).resolve()
        if self.root not in p.parents:
            raise ValueError("invalid storage key")
        return p

    def new_key(self, center_id):
        now = utcnow()
        return f"{int(center_id)}/{now:%Y}/{now:%m}/{secrets.token_hex(16)}"

    def save(self, key, data: bytes):
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, p)

    def read(self, key) -> bytes:
        with open(self._path(key), "rb") as f:
            return f.read()

    def path(self, key):
        return self._path(key)

    def delete(self, key):
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            pass

    def exists(self, key):
        return self._path(key).exists()


_storage = {}


def get_storage():
    root = current_app.config["STORAGE_ROOT"]
    if root not in _storage:
        _storage[root] = LocalStorage(root)
    return _storage[root]


def sha256(data: bytes):
    return hashlib.sha256(data).hexdigest()
