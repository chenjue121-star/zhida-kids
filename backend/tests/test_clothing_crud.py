"""Characterization tests for clothing CRUD routes.

These tests LOCK the current behavior of app/routers/clothing.py.
Do NOT change production code to make tests pass; adjust assertions
if the real endpoint behaves differently from the initial assumption.
"""


def test_list_clothing_returns_child_items(client):
    child_id = client.seed["child_id"]
    resp = client.get("/clothing", params={"child_id": child_id})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    assert {i["type"] for i in items} == {"top", "pants"}


def test_list_clothing_unknown_child_404(client):
    resp = client.get("/clothing", params={"child_id": 999999})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "宝贝不存在"


def test_create_clothing(client):
    child_id = client.seed["child_id"]
    payload = {
        "child_id": child_id, "type": "shoes", "main_color": "red",
        "thickness": "normal", "pattern": "solid",
        "season": ["all"], "style_tags": ["sporty"],
    }
    resp = client.post("/clothing", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["type"] == "shoes"
    assert body["main_color"] == "red"


def test_get_clothing(client):
    top_id = client.seed["top_id"]
    resp = client.get(f"/clothing/{top_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == top_id


def test_get_clothing_not_owned_404(client):
    resp = client.get("/clothing/999999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "衣物不存在"


def test_update_clothing_partial(client):
    top_id = client.seed["top_id"]
    resp = client.put(f"/clothing/{top_id}", json={"main_color": "black"})
    assert resp.status_code == 200
    assert resp.json()["main_color"] == "black"


def test_mark_worn_increments_count(client):
    top_id = client.seed["top_id"]
    resp = client.post(f"/clothing/{top_id}/wear")
    assert resp.status_code == 200
    body = resp.json()
    assert body["wear_count"] == 1
    assert body["last_worn_at"] is not None


def test_delete_clothing(client):
    top_id = client.seed["top_id"]
    resp = client.delete(f"/clothing/{top_id}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True}
    assert client.get(f"/clothing/{top_id}").status_code == 404
