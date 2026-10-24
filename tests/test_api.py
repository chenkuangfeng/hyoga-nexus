from fastapi.testclient import TestClient
from nexus_api.main import app

client = TestClient(app)

def test_health():
    assert client.get("/api/v1/health").json()["status"] == "ok"

def test_unimplemented_capabilities_are_not_advertised_as_ready():
    response = client.get("/api/v1/capabilities")
    assert response.status_code == 200
    assert all(item["status"] == "planned" for group in response.json().values() for item in group)
