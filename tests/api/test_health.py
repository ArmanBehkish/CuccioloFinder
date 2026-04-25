def test_health_response_shape(client):
    response = client.get("/api/health")

    assert response.status_code == 200

    data = response.json()
    assert set(data.keys()) == {"status", "db", "models", "backends"}
    assert data["status"] in {"ok", "degraded"}
    assert isinstance(data["db"], bool)

    models = data["models"]
    assert set(models.keys()) == {"mistral", "groq"}
    assert isinstance(models["mistral"], dict)
    assert isinstance(models["mistral"]["loaded"], bool)
    assert set(models["groq"].keys()) == {"configured", "responsive"}
    assert isinstance(models["groq"]["configured"], bool)
    # responsive is bool when at least one backend is groq, None otherwise
    assert models["groq"]["responsive"] is None or isinstance(
        models["groq"]["responsive"], bool
    )

    backends = data["backends"]
    assert set(backends.keys()) == {"search", "translation"}
    assert backends["search"] in {"mistral", "groq"}
    assert backends["translation"] in {"mistral", "groq"}
