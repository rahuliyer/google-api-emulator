def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_reset_reseeds_database(client):
    response = client.post("/reset")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    again = client.post("/reset")
    assert again.json() == {"ok": True}
