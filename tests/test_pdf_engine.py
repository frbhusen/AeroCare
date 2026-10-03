import io

from tests.test_billing_helpers import BASE, make_patient, new_invoice


def _png():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), (15, 118, 110)).save(buf, "PNG")
    return buf.getvalue()


def test_render_document_arabic_and_english():
    from backend.app.services.pdf import render_document, visual
    sections = [
        {"type": "heading", "text": "معلومات المريض"},
        {"type": "key_values", "items": [["الاسم", "محمد العلي"], ["Code", "PAT-000001"], ["العمر", "30"]]},
        {"type": "table", "columns": ["الوصف", "الكمية", "المبلغ"],
         "rows": [["حشوة سن Filling", "1", "100.00"]] * 60, "widths": [3, 1, 1], "align": ["start", "center", "end"]},
        {"type": "totals", "items": [["الإجمالي", "100.00", True]]},
        {"type": "paragraph", "text": "نص عربي طويل للتجربة " * 50 + "\nسطر جديد"},
        {"type": "note", "text": "ملاحظة"}, {"type": "spacer", "height": 4},
        {"type": "image", "data": _png(), "width": 30, "caption": "صورة"},
        {"type": "signature", "labels": ["الطبيب", "المريض"]}, {"type": "page_break"},
        {"type": "paragraph", "text": "Second page"}, {"type": "unknown"},
    ]
    center = {"name": "مركز الشفاء الطبي", "primary_color": "#123456", "document_footer": "شكراً لكم",
              "address": "دمشق", "phone": "+963 11 000"}
    data = render_document(center, {"name": "طب الأسنان", "color": "#aa0000"}, "invoice", "فاتورة", sections,
                           lang="ar", logo_bytes=_png(), subtitle="INV-000001")
    assert data.startswith(b"%PDF") and len(data) > 2000
    en = render_document({"name": "Center"}, None, "invoice", "Invoice", sections, lang="en")
    assert en.startswith(b"%PDF")
    assert visual("abc") == "abc" and visual("سلام") != "سلام"


def test_templates_crud_inheritance_and_scope(app, world, client_for):
    a, b = world["A"], world["B"]
    mgr = client_for(a["users"]["manager"])
    r = mgr.post(f"{BASE}/templates", json={"kind": "invoice", "title": "Center invoice", "footer_text": "Thanks",
                                            "accent_color": "#112233"})
    assert r.status_code == 201, r.get_json()
    center_t = r.get_json()
    assert mgr.post(f"{BASE}/templates", json={"kind": "invoice"}).status_code == 409  # one per level
    dept = a["departments"]["dentistry"]
    head = client_for(a["users"]["dent_head"])
    r = head.post(f"{BASE}/templates", json={"kind": "invoice", "department_id": dept, "title": "Dental invoice",
                                             "show_logo": False})
    assert r.status_code == 201
    dept_t = r.get_json()
    eff = mgr.get(f"{BASE}/templates/effective?kind=invoice&department_id={dept}").get_json()
    assert eff["title"] == "Dental invoice" and eff["footer_text"] == "Thanks" and eff["accent_color"] == "#112233"
    assert eff["show_logo"] is False and eff["sources"] == ["default", "center", "department"]
    eff = mgr.get(f"{BASE}/templates/effective?kind=invoice&department_id={a['departments']['dermatology']}"
                  ).get_json()
    assert eff["title"] == "Center invoice" and eff["show_logo"] is True
    eff = mgr.get(f"{BASE}/templates/effective?kind=receipt").get_json()
    assert eff["sources"] == ["default"]
    # department manager cannot edit center template or other departments
    assert head.post(f"{BASE}/templates", json={"kind": "receipt"}).status_code == 403
    assert head.put(f"{BASE}/templates/{center_t['id']}", json={"version": 1, "title": "x"}).status_code == 403
    assert head.post(f"{BASE}/templates", json={"kind": "receipt", "department_id": a["departments"]["dermatology"]}
                     ).status_code == 404
    # doctor lacks settings.edit
    doc = client_for(a["users"]["dent_doc1"])
    assert doc.post(f"{BASE}/templates", json={"kind": "receipt", "department_id": dept}).status_code == 403
    # validation
    assert mgr.post(f"{BASE}/templates", json={"kind": "bogus"}).status_code == 422
    assert mgr.post(f"{BASE}/templates", json={"kind": "receipt", "accent_color": "red"}).status_code == 422
    # version conflict
    r = head.put(f"{BASE}/templates/{dept_t['id']}", json={"version": dept_t["version"], "title": "New"})
    assert r.status_code == 200 and r.get_json()["title"] == "New"
    assert head.put(f"{BASE}/templates/{dept_t['id']}", json={"version": dept_t["version"], "title": "Old"}
                    ).status_code == 409
    # cross tenant
    other = client_for(b["users"]["manager"])
    assert other.get(f"{BASE}/templates/{center_t['id']}").status_code == 404
    assert other.delete(f"{BASE}/templates/{center_t['id']}").status_code == 404
    # delete + undo; re-create after delete allowed (partial unique index ignores staged rows)
    r = mgr.delete(f"{BASE}/templates/{center_t['id']}")
    assert r.status_code == 202
    assert mgr.post(f"{BASE}/templates", json={"kind": "invoice", "title": "Replacement"}).status_code == 201
    lst = mgr.get(f"{BASE}/templates?kind=invoice").get_json()["items"]
    assert {t["title"] for t in lst} == {"Replacement", "New"}


def test_invoice_and_receipt_pdfs(app, world, client_for):
    a = world["A"]
    pid = make_patient(app, a, "dent1", "علي حسن")
    c = client_for(a["users"]["rec_dent"])
    client_for(a["users"]["manager"]).post(f"{BASE}/templates", json={"kind": "invoice", "footer_text": "شكراً لزيارتكم"})
    inv = new_invoice(c, a, pid, items=[{"description": "حشوة تجميلية", "unit_price": "250000",
                                         "discount_percent": 10},
                                        {"description": "Cleaning", "unit_price": "50000"}],
                      notes="ملاحظات الفاتورة").get_json()
    for lang in ("ar", "en"):
        r = c.get(f"{BASE}/invoices/{inv['id']}/pdf?lang={lang}")
        assert r.status_code == 200 and r.mimetype == "application/pdf"
        assert r.data.startswith(b"%PDF")
        assert "inline" in r.headers["Content-Disposition"]
    # receipt needs a payment
    r = c.get(f"{BASE}/invoices/{inv['id']}/receipt")
    assert r.status_code == 422
    p1 = c.post(f"{BASE}/invoices/{inv['id']}/payments", json={"amount": "100000"}).get_json()["payment"]
    c.post(f"{BASE}/invoices/{inv['id']}/payments", json={"amount": "50000"})
    for q in ("?lang=ar", f"?payment_id={p1['id']}&lang=ar", "?lang=en"):
        r = c.get(f"{BASE}/invoices/{inv['id']}/receipt{q}")
        assert r.status_code == 200 and r.data.startswith(b"%PDF"), q
    assert c.get(f"{BASE}/invoices/{inv['id']}/receipt?payment_id=999999999").status_code == 404

