"""Concurrent decrements must never drive stock negative (row locks on item + lots)."""
import threading

from tests.test_inventory_core import API, level, loc_id, mk_item, receive


def test_concurrent_use_never_negative(app, world, client_for):
    a = world["A"]
    users = ["manager", "dent_head", "dent_doc1", "rec_dent1", "rec_dent", "rec_center", "rec_multi"]
    clients = [client_for(a["users"][u]) for u in users]
    head = clients[1]
    loc = loc_id(head, "clinic", a["clinics"]["dent1"])
    it = mk_item(head, name="Cartridges")
    receive(head, loc, it["id"], 4, lot_code="X")
    receive(head, loc, it["id"], 6, lot_code="Y")
    results = []
    barrier = threading.Barrier(len(clients))

    def worker(c):
        barrier.wait()
        r = c.post(f"{API}/use", json={"location_id": loc, "item_id": it["id"], "quantity": 3})
        results.append(r.status_code)

    threads = [threading.Thread(target=worker, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert sorted(results) == [200, 200, 200, 409, 409, 409, 409], results
    assert level(head, loc, it["id"]) == "1"
    mv = head.get(f"{API}/movements", query_string={"item_id": it["id"], "type": "use"}).get_json()["items"]
    assert sum(-float(m["quantity"]) for m in mv) == 9
