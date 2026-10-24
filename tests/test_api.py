from fastapi.testclient import TestClient
from nexus_api.main import app

client = TestClient(app)

def test_health():
    assert client.get("/api/v1/health").json()["status"] == "ok"

def test_unimplemented_capabilities_are_not_advertised_as_ready():
    response = client.get("/api/v1/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert data["runtimes"][0]["status"] == "requires_configuration"
    assert all(item["status"] == "planned" for item in data["runtimes"][1:])
    assert all(item["status"] == "planned" for item in data["channels"][1:])
    capabilities = client.get('/api/v1/runtime-capabilities').json()
    assert capabilities['sandbox']['code_execution'] is False
    assert capabilities['sandbox']['shell'] is False
    assert capabilities['native']['streaming'] is True
