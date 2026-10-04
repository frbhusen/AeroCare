"""Shared PDF engine (owned by billing; called by every module that prints official documents).

Main entry:

    from backend.app.services.pdf import render_document
    pdf_bytes = render_document(
        center=center,            # HealthCenter row (or a dict with the same keys) - branding
        department=department,    # Department row / dict or None
        kind="invoice",           # template kind (see documents.TEMPLATE_DEFAULTS)
        title="Invoice",          # document title (already localized)
        sections=[...],           # list of section dicts (below)
        lang="ar",                # "ar" (RTL) or "en"
        template=None,            # dict from documents.get_template(); defaults applied when None
        logo_bytes=None,          # image bytes for the header logo (documents.render() loads it)
        subtitle=None,            # e.g. "INV-000012"
    )

Most callers should use `services.documents.render(center_id, department_id, kind, title, sections, lang)`
which loads center/department/template/logo itself.

Section dicts (any order, all text may be Arabic, English or mixed):
    {"type": "heading",    "text": "Items"}
    {"type": "paragraph",  "text": "Free text...\nNew lines kept", "size": 9}
    {"type": "key_values", "items": [["Patient", "Ali"], ["Code", "PAT-000001"]], "columns": 2}
    {"type": "table",      "columns": ["Description", "Qty", "Price"], "rows": [["X", "1", "10.00"]],
                           "widths": [3, 1, 1],            # optional relative widths
                           "align": ["start", "end", "end"]}  # optional: start | center | end
    {"type": "totals",     "items": [["Subtotal", "100.00"], ["Total", "90.00", True]]}  # 3rd = bold
    {"type": "signature",  "labels": ["Doctor", "Patient"]}
    {"type": "note",       "text": "small grey text"}
    {"type": "spacer",     "height": 6}                    # millimetres
    {"type": "image",      "data": b"...", "width": 60}    # millimetres; optional "caption"
    {"type": "page_break"}

"start"/"end" alignment is logical: in Arabic documents start = right. Table columns are mirrored
for RTL automatically. Arabic text is shaped with arabic_reshaper and reordered with python-bidi.

Fonts: PDF_FONT_PATH (+ optional PDF_FONT_BOLD_PATH) env vars, then DejaVuSans / Noto (Linux),
then Tahoma / Arial (Windows). Without any TTF the engine falls back to Helvetica (no Arabic glyphs).
"""
import io
import os
import re
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from backend.app.core.timeutil import local_now

FONT, FONT_BOLD = "HCSans", "HCSans-Bold"
_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_fonts = None  # (regular, bold) registered names

_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
     "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf"),
    ("/usr/share/fonts/noto/NotoSansArabic-Regular.ttf", "/usr/share/fonts/noto/NotoSansArabic-Bold.ttf"),
    ("C:/Windows/Fonts/tahoma.ttf", "C:/Windows/Fonts/tahomabd.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
]

# Built-in labels used by the engine itself and by billing documents. Other modules pass their own
# localized strings; they may also use t() for these common keys.
LABELS = {
    "page": {"en": "Page {n} of {total}", "ar": "صفحة {n} من {total}"},
    "printed_at": {"en": "Printed {dt}", "ar": "طُبع في {dt}"},
    "signature": {"en": "Signature", "ar": "التوقيع"},
}


def t(key, lang="en", **kw):
    entry = LABELS.get(key, {})
    s = entry.get(lang) or entry.get("en") or key
    return s.format(**kw) if kw else s


# ---------------------------------------------------------------- fonts / text
def _find_fonts():
    env = os.environ.get("PDF_FONT_PATH")
    if env and os.path.isfile(env):
        bold = os.environ.get("PDF_FONT_BOLD_PATH")
        return env, bold if bold and os.path.isfile(bold) else env
    for reg, bold in _CANDIDATES:
        if os.path.isfile(reg):
            return reg, bold if os.path.isfile(bold) else reg
    return None, None


def ensure_fonts():
    """Register the document fonts once per process. Returns (regular, bold) font names."""
    global _fonts
    if _fonts is not None:
        return _fonts
    reg, bold = _find_fonts()
    if reg:
        try:
            pdfmetrics.registerFont(TTFont(FONT, reg))
            pdfmetrics.registerFont(TTFont(FONT_BOLD, bold))
            _fonts = (FONT, FONT_BOLD)
            return _fonts
        except Exception:  # unreadable/unsupported font file -> fall back
            pass
    _fonts = ("Helvetica", "Helvetica-Bold")
    return _fonts


def has_arabic(s):
    return bool(s) and bool(_ARABIC_RE.search(s))


def visual(s):
    """Logical -> visual order for one line (shapes Arabic letters, applies the bidi algorithm)."""
    s = "" if s is None else str(s)
    if not has_arabic(s):
        return s
    import arabic_reshaper
    from bidi.algorithm import get_display
    return get_display(arabic_reshaper.reshape(s))


def _wrap_lines(text, font, size, width):
    """Split logical text into visual lines that fit `width` (points). Wrapping happens on the
    reshaped logical text so RTL paragraphs keep the right line order."""
    out = []
    for raw in str(text or "").split("\n"):
        if not has_arabic(raw):
            out.extend(simpleSplit(raw, font, size, width) or [""])
            continue
        import arabic_reshaper
        from bidi.algorithm import get_display
        shaped = arabic_reshaper.reshape(raw)
        for line in simpleSplit(shaped, font, size, width) or [""]:
            out.append(get_display(line))
    return out


def _para(text, style, width):
    # Table cells have 6pt padding on each side: wrap to the *inner* width ourselves so the Paragraph
    # never re-wraps an already visual-ordered (bidi) line, which would scramble Arabic word order.
    lines = _wrap_lines(text, style.fontName, style.fontSize, max(width - 14, 10))
    return Paragraph("<br/>".join(escape(x) for x in lines) or "&nbsp;", style)


def _color(value, default="#0f766e"):
    try:
        return colors.HexColor(value if value and re.fullmatch(r"#[0-9a-fA-F]{6}", value) else default)
    except Exception:
        return colors.HexColor(default)


def _get(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ---------------------------------------------------------------- canvas
def _numbered_canvas(footer_cb):
    class NumberedCanvas(rl_canvas.Canvas):
        """Two-pass canvas so the footer can print 'Page n of total'."""

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._saved = []

        def showPage(self):
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved)
            for state in self._saved:
                self.__dict__.update(state)
                footer_cb(self, self._pageNumber, total)
                super().showPage()
            super().save()
    return NumberedCanvas


# ---------------------------------------------------------------- main entry
def render_document(center, department=None, kind="document", title="", sections=(), lang="en", template=None,
                    logo_bytes=None, subtitle=None, page_size="A4"):
    from backend.app.services.documents import TEMPLATE_DEFAULTS, merge_template
    regular, bold = ensure_fonts()
    rtl = lang == "ar"
    tpl = template or merge_template(TEMPLATE_DEFAULTS.get(kind, {}))
    accent = _color(tpl.get("accent_color") or _get(department, "color") or _get(center, "primary_color"))
    size = A5 if page_size == "A5" else A4
    margin = 14 * mm
    width = size[0] - 2 * margin
    start, end = (TA_RIGHT, TA_LEFT) if rtl else (TA_LEFT, TA_RIGHT)

    def style(name, fs=9.5, font=regular, align=start, color=colors.black, leading=None):
        return ParagraphStyle(name, fontName=font, fontSize=fs, leading=leading or fs * 1.35, alignment=align,
                              textColor=color)

    st = {
        "body": style("body"), "bold": style("bold", font=bold),
        "end": style("end", align=end), "end_bold": style("end_bold", font=bold, align=end),
        "center": style("center", align=TA_CENTER),
        "h": style("h", fs=11.5, font=bold, color=accent), "small": style("small", fs=8, color=colors.grey),
        "title": style("title", fs=16, font=bold, align=TA_CENTER, color=accent),
        "sub": style("sub", fs=10, align=TA_CENTER, color=colors.HexColor("#444444")),
        "th": style("th", fs=9, font=bold, color=colors.white),
    }
    align_map = {"start": start, "end": end, "center": TA_CENTER}
    story = []

    # ---- header: logo + center/department identity
    name_lines = [_para(_get(center, "name", ""), style("cn", fs=14, font=bold, color=accent), width * 0.7)]
    dept_name = _get(department, "name")
    if dept_name:
        name_lines.append(_para(dept_name, style("dn", fs=10.5, font=bold), width * 0.7))
    contact = " | ".join(x for x in (_get(center, "address"), _get(center, "phone")) if x)
    if contact:
        name_lines.append(_para(contact, st["small"], width * 0.7))
    logo_cell = ""
    if logo_bytes and tpl.get("show_logo", True):
        try:
            img = ImageReader(io.BytesIO(logo_bytes))
            iw, ih = img.getSize()
            h = 18 * mm
            w = min(40 * mm, h * iw / ih if ih else h)
            logo_cell = Image(io.BytesIO(logo_bytes), width=w, height=w * ih / iw if iw else h)
        except Exception:
            logo_cell = ""
    cells = [name_lines, logo_cell] if not rtl else [logo_cell, name_lines]
    widths = [width * 0.72, width * 0.28] if not rtl else [width * 0.28, width * 0.72]
    head = Table([cells], colWidths=widths)
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("ALIGN", (1 if not rtl else 0, 0), (1 if not rtl else 0, 0),
                               "RIGHT" if not rtl else "LEFT"),
                              ("LINEBELOW", (0, 0), (-1, 0), 2, accent),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story.append(head)
    if tpl.get("header_text"):
        story += [Spacer(1, 2 * mm), _para(tpl["header_text"], st["small"], width)]
    story.append(Spacer(1, 4 * mm))
    story.append(_para(title or tpl.get("title") or "", st["title"], width))
    if subtitle:
        story.append(_para(subtitle, st["sub"], width))
    story.append(Spacer(1, 4 * mm))

    for sec in sections or ():
        story.extend(_section(sec, st, width, rtl, accent, align_map, regular, bold, style))

    footer_text = tpl.get("footer_text") or _get(center, "document_footer") or ""
    printed = t("printed_at", lang, dt=local_now().strftime("%m/%d/%Y %H:%M"))

    def footer(cv, n, total):
        cv.saveState()
        cv.setStrokeColor(accent)
        cv.setLineWidth(0.6)
        cv.line(margin, 15 * mm, size[0] - margin, 15 * mm)
        cv.setFont(regular, 7.5)
        cv.setFillColor(colors.HexColor("#555555"))
        y = 11 * mm
        if footer_text:
            for line in _wrap_lines(footer_text, regular, 7.5, width)[:2]:
                cv.drawCentredString(size[0] / 2, y, line)
                y -= 3.3 * mm
        left, right = visual(printed), visual(t("page", lang, n=n, total=total))
        if rtl:
            left, right = right, left
        cv.drawString(margin, 5 * mm, left)
        cv.drawRightString(size[0] - margin, 5 * mm, right)
        cv.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=size, leftMargin=margin, rightMargin=margin, topMargin=12 * mm,
                            bottomMargin=20 * mm, title=visual(title or ""), author=visual(_get(center, "name", "")),
                            creator="Health Center Platform")
    doc.build(story, canvasmaker=_numbered_canvas(footer))
    return buf.getvalue()


def _section(sec, st, width, rtl, accent, align_map, regular, bold, style):
    typ = sec.get("type")
    if typ == "heading":
        return [Spacer(1, 2 * mm), _para(sec.get("text", ""), st["h"], width), Spacer(1, 1.5 * mm)]
    if typ == "paragraph":
        s = st["body"] if not sec.get("size") else style(f"p{sec['size']}", fs=float(sec["size"]))
        return [_para(sec.get("text", ""), s, width), Spacer(1, 2 * mm)]
    if typ == "note":
        return [_para(sec.get("text", ""), st["small"], width), Spacer(1, 1.5 * mm)]
    if typ == "spacer":
        return [Spacer(1, float(sec.get("height", 5)) * mm)]
    if typ == "page_break":
        return [PageBreak()]
    if typ == "key_values":
        return _key_values(sec, st, width, rtl)
    if typ == "table":
        return _table(sec, st, width, rtl, accent, align_map)
    if typ == "totals":
        return _totals(sec, st, width, rtl, accent)
    if typ == "signature":
        labels = sec.get("labels") or ["Signature"]
        n = len(labels)
        cw = width / n
        row = [[Spacer(1, 12 * mm), _para("_" * 24, st["center"], cw), _para(lb, st["center"], cw)]
               for lb in labels]
        if rtl:
            row.reverse()
        tbl = Table([row], colWidths=[cw] * n)
        return [Spacer(1, 6 * mm), KeepTogether(tbl)]
    if typ == "image":
        try:
            data = sec["data"]
            img = ImageReader(io.BytesIO(data))
            iw, ih = img.getSize()
            w = min(float(sec.get("width", 80)) * mm, width)
            out = [Image(io.BytesIO(data), width=w, height=w * ih / iw)]
            if sec.get("caption"):
                out.append(_para(sec["caption"], st["small"], width))
            return out + [Spacer(1, 2 * mm)]
        except Exception:
            return []
    return []


def _key_values(sec, st, width, rtl):
    items = [(str(k), "" if v is None else str(v)) for k, v in (sec.get("items") or [])]
    if not items:
        return []
    cols = max(1, min(3, int(sec.get("columns", 2))))
    pair_w = width / cols
    lw, vw = pair_w * 0.38, pair_w * 0.62
    pairs = [[_para(k, st["bold"], lw), _para(v, st["body"], vw)] for k, v in items]
    while len(pairs) % cols:
        pairs.append(["", ""])
    rows = []
    for i in range(0, len(pairs), cols):
        chunk = pairs[i:i + cols]
        if rtl:  # mirror: first pair on the right, value left of its label
            chunk = [[val, lab] for lab, val in reversed(chunk)]
        rows.append([c for pair in chunk for c in pair])
    widths = ([vw, lw] if rtl else [lw, vw]) * cols
    tbl = Table(rows, colWidths=widths)
    tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                             ("TOPPADDING", (0, 0), (-1, -1), 2)]))
    return [tbl, Spacer(1, 3 * mm)]


def _table(sec, st, width, rtl, accent, align_map):
    columns = [str(c) for c in (sec.get("columns") or [])]
    if not columns:
        return []
    n = len(columns)
    rel = sec.get("widths") or [1] * n
    total = float(sum(rel)) or 1
    widths = [width * float(r) / total for r in rel]
    aligns = sec.get("align") or ["start"] * n
    body_styles = []
    for a in aligns:
        al = align_map.get(a, align_map["start"])
        body_styles.append(ParagraphStyle(f"td{al}", parent=st["body"], alignment=al))
    head_styles = [ParagraphStyle(f"th{s.alignment}", parent=st["th"], alignment=s.alignment) for s in body_styles]
    data = [[_para(c, head_styles[i], widths[i]) for i, c in enumerate(columns)]]
    for r in sec.get("rows") or []:
        r = list(r) + [""] * (n - len(r))
        data.append([_para("" if v is None else str(v), body_styles[i], widths[i]) for i, v in enumerate(r[:n])])
    if rtl:
        data = [list(reversed(r)) for r in data]
        widths = list(reversed(widths))
    tbl = Table(data, colWidths=widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), accent),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7f7")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return [tbl, Spacer(1, 3 * mm)]


def _totals(sec, st, width, rtl, accent):
    rows = []
    bold_rows = []
    lw, vw = width * 0.25, width * 0.2
    for i, it in enumerate(sec.get("items") or []):
        label, value = str(it[0]), "" if it[1] is None else str(it[1])
        b = len(it) > 2 and bool(it[2])
        ls = st["end_bold"] if b else st["end"]
        cells = [_para(label, ls, lw), _para(value, ls, vw)]
        rows.append(["", *cells] if not rtl else [*reversed(cells), ""])
        if b:
            bold_rows.append(i)
    if not rows:
        return []
    widths = [width - lw - vw, lw, vw] if not rtl else [vw, lw, width - lw - vw]
    tbl = Table(rows, colWidths=widths)
    cmds = [("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
    for i in bold_rows:
        cols = (1, 2) if not rtl else (0, 1)
        cmds.append(("LINEABOVE", (cols[0], i), (cols[1], i), 0.8, accent))
    tbl.setStyle(TableStyle(cmds))
    return [KeepTogether(tbl), Spacer(1, 3 * mm)]


def format_money(amount, currency=None):
    """'1,250.50 SYP' (Decimal/str/number in, display string out)."""
    from decimal import Decimal
    try:
        d = Decimal(str(amount)).quantize(Decimal("0.01"))
    except Exception:
        return str(amount)
    s = f"{d:,.2f}"
    return f"{s} {currency}" if currency else s


def format_dt(dt, with_time=True):
    """Local (Asia/Damascus) display, month/day order (spec §68): MM/DD/YYYY HH:MM."""
    from backend.app.core.timeutil import to_local
    if dt is None:
        return ""
    if isinstance(dt, datetime):
        dt = to_local(dt)
        return dt.strftime("%m/%d/%Y %H:%M" if with_time else "%m/%d/%Y")
    return dt.strftime("%m/%d/%Y") if hasattr(dt, "strftime") else str(dt)
