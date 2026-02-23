import os

import httpx
import pytest

API_URL = os.environ.get("API_URL", "http://localhost:8000")


@pytest.fixture(scope="session")
def client():
    with httpx.Client(base_url=API_URL) as c:
        yield c
