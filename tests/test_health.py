
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint_returns_200():
    response = client.get("/api/v1/health")

    assert response.status_code == 200


def test_health_endpoint_returns_expected_response():
    response = client.get("/api/v1/health")

    assert response.json() == {"status": "healthy"}


def test_health_endpoint_is_documented_in_openapi():
    schema = app.openapi()

    assert "/api/v1/health" in schema["paths"]
    assert "get" in schema["paths"]["/api/v1/health"]

