def test_health_response_shape(client):
    response = client.get("/api/health")

    assert response.status_code == 200

    data = response.json()
    assert set(data.keys()) == {"status", "db", "search_model"}
    assert data["status"] in {"ok", "degraded"}
    assert isinstance(data["db"], bool)
    assert isinstance(data["search_model"], bool)
