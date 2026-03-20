"""Integration tests for the FastAPI routes."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.auth_client import AuthError
from app.services.routing_client import RoutingConnectionError


@pytest.fixture
def client():
    return TestClient(app)


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


VALID_PAYLOAD = {
    "points": {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-95.26, 29.72]},
                "properties": {"name": "Houston"},
            }
        ],
    },
    "voyage": {"departurePort": "USHOU", "destinationPort": "NLRTM", "etd": "2025-09-01T00:00:00Z"},
    "vesselParameters": {
        "name": "MV Test",
        "imo": "1234567",
        "vesselType": "container",
        "cargoType": "general",
        "lengthOverall": 300.0,
        "beam": 48.0,
        "draft": 14.0,
        "fuelConsumptionCurve": [],
        "safetyMargins": {"underKeel": 1.5},
        "ciiRating": "B",
    },
    "costs": {"vesselOperatingCost": 15000.0, "fuelCosts": {"VLSFO": 650.0}},
    "weatherSource": "ECMWF",
    "config": {"avoidPiracyZones": True, "useGreatCircle": False},
    "speed": 14.5,
    "optimizationType": "cost",
    "restrictions": {"exclusionZones": [], "conditionalAreas": [], "weatherLimits": {}},
}


def test_route_returns_200_on_success(client):
    with patch("app.main._routing_client.compute_route", new_callable=AsyncMock) as mock_route:
        mock_route.return_value = [{"type": "result", "route": {}}]
        response = client.post("/route", json=VALID_PAYLOAD)

    assert response.status_code == 200
    assert response.json() == [{"type": "result", "route": {}}]


def test_route_returns_502_on_auth_error(client):
    with patch("app.main._routing_client.compute_route", new_callable=AsyncMock) as mock_route:
        mock_route.side_effect = AuthError(401, "Unauthorized")
        response = client.post("/route", json=VALID_PAYLOAD)

    assert response.status_code == 502


def test_route_returns_502_on_connection_error(client):
    with patch("app.main._routing_client.compute_route", new_callable=AsyncMock) as mock_route:
        mock_route.side_effect = RoutingConnectionError("timeout")
        response = client.post("/route", json=VALID_PAYLOAD)

    assert response.status_code == 502


def test_route_returns_422_on_missing_field(client):
    payload = {**VALID_PAYLOAD}
    del payload["speed"]
    response = client.post("/route", json=payload)
    assert response.status_code == 422


def test_correlation_id_echoed_in_response(client):
    with patch("app.main._routing_client.compute_route", new_callable=AsyncMock) as mock_route:
        mock_route.return_value = []
        response = client.post(
            "/route",
            json=VALID_PAYLOAD,
            headers={"X-Correlation-ID": "test-corr-123"},
        )

    assert response.headers.get("X-Correlation-ID") == "test-corr-123"
