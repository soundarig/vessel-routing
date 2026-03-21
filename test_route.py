"""
End-to-end test using the exact ABB API payload format.
Run from vessel-routing/ directory: python3 test_route.py
"""
import json
import urllib.request
import urllib.parse

BASE = "http://localhost:8300"

# Step 1 — get token
print("=== Step 1: Get token ===")
data = urllib.parse.urlencode({"username": "admin", "password": "admin123"}).encode()
req = urllib.request.Request(
    f"{BASE}/auth/token", data=data,
    headers={"Content-Type": "application/x-www-form-urlencoded"}
)
with urllib.request.urlopen(req) as resp:
    token_resp = json.loads(resp.read())

token = token_resp["access_token"]
print(f"Token type : {token_resp['token_type']}")
print(f"Expires in : {token_resp['expires_in']}s")
print(f"Token      : {token[:50]}...")

# Step 2 — call /route with exact ABB payload format
print("\n=== Step 2: POST /route ===")
payload = {
    "points": [
        {
            "type": "Feature",
            "properties": {"name": "Houston, TX", "port": "USHOU-2380"},
            "geometry": {"type": "Point", "coordinates": [-95.2641144, 29.7262421]}
        },
        {
            "type": "Feature",
            "properties": {"name": "Rotterdam (NLRTM)", "port": "NLRTM-2745", "forceRhumbLine": False},
            "geometry": {"type": "Point", "coordinates": [4.0710449, 51.9672394]}
        }
    ],
    "id": "test-001",
    "voyage": {
        "ports": [
            {"type": "Feature", "properties": None, "geometry": {"type": "Point", "coordinates": [8.577543, 53.535847]}},
            {"portId": "NLRTM-2745"}
        ]
    },
    "etd": "2025-09-20T19:20:30.45Z",
    "vesselParameters": {
        "vesselName": "MV Test",
        "imo": "8814275",
        "vesselType": "DryBulkCarrier",
        "cargo": {
            "loadCondition": "Loaded",
            "loadState": "Packaged",
            "dangerousCargo": []
        },
        "measurements": {
            "lengthOverall": 100,
            "beam": 20,
            "draft": {"aft": 10, "fore": 10},
            "airDraft": 10,
            "grossTonnage": 100000,
            "deadweight": 250000
        },
        "fuelCurve": {
            "otherFuelConsumption": 1,
            "values": [{"speed": 8, "fuelUsage": 2.6}, {"speed": 12, "fuelUsage": 9.2}]
        },
        "safetyMargins": {"port": 0, "starboard": 0, "underKeel": 0, "air": 0, "aft": 0, "forward": 0},
        "cii": {"yearToDateDistance": 10, "yearToDateCo2Emissions": 0}
    },
    "costs": {
        "vesselCosts": 25000,
        "fuelCosts": 800,
        "ecaFuelCosts": 800,
        "otherFuelCosts": 800
    },
    "weatherSource": {"type": "Forecast", "version": "2025-09-20T00:00:00Z"},
    "config": {
        "hoursBetweenRouteWaypoints": 6,
        "avoidCoastalAreas": True,
        "followShortestNavigableRoute": False,
        "groundingCheckMode": "Off"
    },
    "speed": 10,
    "optimizationType": "Fuel",
    "restrictions": {
        "northVertex": 80,
        "southVertex": 80,
        "conditionalAreas": {
            "defaultAreas": ["SpeedLimit", "EmissionControl"],
            "areaOverrides": [],
            "customAreas": []
        },
        "weatherLimits": []
    }
}

body = json.dumps(payload).encode()
req = urllib.request.Request(
    f"{BASE}/route", data=body,
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "X-Correlation-ID": "test-001"
    }
)

try:
    with urllib.request.urlopen(req, timeout=180) as resp:
        result = json.loads(resp.read())
        print(f"Status : {resp.status}")
        print(f"Result : {json.dumps(result, indent=2)}")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"HTTP {e.code}: {body}")
