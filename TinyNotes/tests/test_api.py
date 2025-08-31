from fastapi.testclient import TestClient
from app.main import app, DEV_API_KEY

client = TestClient(app)
headers = {"X-API-Key": DEV_API_KEY}

def test_create_list_metrics():
    # create note (idempotent)
    r = client.post(
        "/notes",
        headers=headers | {"Idempotency-Key": "k1"},
        json={"content": "hello world"},
    )
    assert r.status_code == 201, r.text
    first = r.json()

    # repeat with same key -> same response
    r2 = client.post(
        "/notes",
        headers=headers | {"Idempotency-Key": "k1"},
        json={"content": "hello world"},
    )
    assert r2.status_code == 201
    assert r2.json() == first

    # list notes contains the note
    r = client.get("/notes", headers=headers)
    assert r.status_code == 200
    notes = r.json()
    assert any(n["id"] == first["id"] for n in notes)

    # health & metrics
    r = client.get("/healthz", headers=headers)
    assert r.status_code == 200
    r = client.get("/metrics", headers=headers)
    assert r.status_code == 200
    snap = r.json()
    assert any(k.startswith("GET ") for k in snap)
