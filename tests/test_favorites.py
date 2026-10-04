"""Clinical favorites: department scoping, center-wide rules, prescription sets, procedures, isolation."""
V = "/api/v1/favorites"


def test_favorites_scope_and_kinds(world, client_for):
    A = world["A"]
    dent = client_for(A["users"]["dent_doc1"])
    derm = client_for(A["users"]["derm_doc"])
    mgr = client_for(A["users"]["manager"])
    rec = client_for(A["users"]["rec_dent"])
    dept = A["departments"]["dentistry"]

    s = dent.post(V, json={"kind": "snippet", "department_id": dept, "field": "examination", "title": "Normal",
                           "body": "Oral mucosa normal."})
    assert s.status_code == 201, s.get_json()
    rx = dent.post(V, json={"kind": "rx_set", "department_id": dept, "title": "Post-extraction",
                            "payload": {"items": [{"medication_name": "Ibuprofen 400mg", "dose": "1 tab", "quantity": 10},
                                                  {"medication_name": "Chlorhexidine", "instructions": "rinse"}]}})
    assert rx.status_code == 201 and len(rx.get_json()["payload"]["items"]) == 2
    proc = dent.post(V, json={"kind": "procedure", "department_id": dept, "title": "Composite filling",
                              "payload": {"price": "150000.00", "code": "D2391"}})
    assert proc.get_json()["payload"]["price"] == "150000.00"
    # Doctors cannot create center-wide favorites; the manager can.
    assert dent.post(V, json={"kind": "diagnosis", "title": "x", "body": "x"}).status_code == 403
    assert mgr.post(V, json={"kind": "diagnosis", "title": "Hypertension",
                             "body": "Essential hypertension (I10)"}).status_code == 201
    # Validation: rx_set needs items, snippet needs body, negative price.
    assert dent.post(V, json={"kind": "rx_set", "department_id": dept, "title": "e",
                              "payload": {"items": []}}).status_code == 422
    assert dent.post(V, json={"kind": "snippet", "department_id": dept, "title": "no body"}).status_code == 422
    assert dent.post(V, json={"kind": "procedure", "department_id": dept, "title": "p",
                              "payload": {"price": "-1"}}).status_code == 422

    def titles(c, **q):
        return {f["title"] for f in c.get(V, query_string=q).get_json()["items"]}

    # Dentistry sees its own + center-wide; dermatology sees only center-wide.
    assert {"Normal", "Post-extraction", "Composite filling", "Hypertension"} <= titles(dent)
    assert titles(derm) == {"Hypertension"}
    assert titles(dent, kind="snippet", field="examination") == {"Normal"}
    # Out-of-scope department -> 404; receptionists (no medical_records.create) cannot add.
    assert derm.post(V, json={"kind": "snippet", "department_id": dept, "title": "x", "body": "x"}).status_code == 404
    assert rec.post(V, json={"kind": "snippet", "department_id": dept, "title": "x", "body": "x"}).status_code == 403
    # Versioned edit, delete + undo, cross-tenant isolation.
    fid = s.get_json()["id"]
    assert dent.patch(f"{V}/{fid}", json={"version": 99, "title": "y"}).status_code == 409
    assert dent.patch(f"{V}/{fid}", json={"version": 1, "title": "Normal exam"}).status_code == 200
    assert derm.patch(f"{V}/{fid}", json={"version": 2, "title": "z"}).status_code == 404
    tok = dent.delete(f"{V}/{fid}").get_json()["undo_token"]
    assert "Normal exam" not in titles(dent)
    assert dent.post("/api/v1/undo", json={"undo_token": tok}).status_code == 200
    assert "Normal exam" in titles(dent)
    other = client_for(world["B"]["users"]["manager"])
    assert other.get(V).get_json()["items"] == []
    assert other.patch(f"{V}/{fid}", json={"version": 2, "title": "hack"}).status_code == 404
