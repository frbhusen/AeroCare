"""Daily cash close: payments per cashier + pharmacy cash sales, scoped, excludes voided payments."""
from tests.test_billing_helpers import make_patient, new_invoice

V = "/api/v1"


def test_cash_close_by_cashier_and_scope(app, world, client_for):
    A = world["A"]
    rec = client_for(A["users"]["rec_dent"])
    mgr = client_for(A["users"]["manager"])
    pid = make_patient(app, A)
    inv = new_invoice(rec, A, pid, items=[{"description": "Visit", "qty": 1, "unit_price": "1000.00"}]).get_json()
    inv = rec.post(f"{V}/billing/invoices/{inv['id']}/issue", json={"version": inv["version"]}).get_json()
    from backend.app.core.timeutil import local_today
    rec.post(f"{V}/billing/invoices/{inv['id']}/payments", json={"amount": "400.00"})
    mgr.post(f"{V}/billing/invoices/{inv['id']}/payments", json={"amount": "100.00"})
    bad = rec.post(f"{V}/billing/invoices/{inv['id']}/payments", json={"amount": "50.00"}).get_json()["payment"]
    r = mgr.post(f"{V}/billing/invoices/{inv['id']}/payments/{bad['id']}/void", json={"reason": "typo", "version": bad.get("version")})
    assert r.status_code == 200, r.get_json()
    today = local_today().isoformat()
    q = {"date_from": today, "date_to": today}
    r = mgr.get(f"{V}/reports/cash_close", query_string=q)
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    by = {row["group"]: row for row in body["rows"]}
    rec_name = next(k for k in by if k.startswith("rec_dent"))
    assert by[rec_name]["payments_cash"] == "400.00" and by[rec_name]["voided_count"] == 1
    assert body["totals"]["total_cash"] == "500.00"
    # Group by day works; Excel export works for the manager.
    assert mgr.get(f"{V}/reports/cash_close", query_string={**q, "group_by": "day"}).status_code == 200
    assert mgr.get(f"{V}/reports/cash_close/export", query_string={**q, "format": "xlsx"}).status_code == 200
    # Scope: a dermatology doctor sees nothing from dentistry; another center sees nothing.
    derm = client_for(A["users"]["derm_doc"]).get(f"{V}/reports/cash_close", query_string=q).get_json()
    assert derm["rows"] == []
    other = client_for(world["B"]["users"]["manager"]).get(f"{V}/reports/cash_close", query_string=q).get_json()
    assert other["rows"] == []
