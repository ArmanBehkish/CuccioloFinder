from loguru import logger


def test_enums_response(client):
    response = client.get("/api/enums")
    data = response.json()
    logger.info(f"GET /api/enums: status={response.status_code} body={data}")

    assert response.status_code == 200

    expected_keys = {
        "source_site", "gender_en", "size_en", "breed_en", "age_en",
        "age_category", "fur_en", "microchip_en", "sterilization_en",
        "vaccine_en", "deworming_en", "good_with_en", "bad_with_en",
        "weight", "post_date", "shelter_since",
    }
    assert set(data.keys()) == expected_keys

    list_fields = expected_keys - {"post_date", "shelter_since"}
    for key in list_fields:
        assert isinstance(data[key], list), f"{key} should be a list"

    for key in ("post_date", "shelter_since"):
        assert isinstance(data[key], dict), f"{key} should be a dict"
        assert "min" in data[key] and "max" in data[key]
