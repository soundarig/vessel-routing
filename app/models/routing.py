from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .geojson import GeoJsonFeatureCollection


class VoyageInfo(BaseModel):
    departurePort: str
    destinationPort: str
    etd: str  # ISO 8601
    model_config = ConfigDict(extra="allow")


class SafetyMargins(BaseModel):
    underKeel: float
    model_config = ConfigDict(extra="allow")


class VesselParameters(BaseModel):
    name: str
    imo: str
    vesselType: str
    cargoType: str
    lengthOverall: float
    beam: float
    draft: float
    fuelConsumptionCurve: list[Any]
    safetyMargins: SafetyMargins
    ciiRating: str
    model_config = ConfigDict(extra="allow")


class Costs(BaseModel):
    vesselOperatingCost: float
    fuelCosts: dict[str, float]
    model_config = ConfigDict(extra="allow")


class Config(BaseModel):
    avoidPiracyZones: bool = False
    useGreatCircle: bool = False
    model_config = ConfigDict(extra="allow")


class WeatherLimits(BaseModel):
    maxWaveHeight: float | None = None
    model_config = ConfigDict(extra="allow")


class Restrictions(BaseModel):
    exclusionZones: list[Any] = []
    conditionalAreas: list[Any] = []
    weatherLimits: WeatherLimits = WeatherLimits()
    model_config = ConfigDict(extra="allow")


class RoutingRequest(BaseModel):
    points: GeoJsonFeatureCollection
    voyage: VoyageInfo
    vesselParameters: VesselParameters
    costs: Costs
    weatherSource: str
    config: Config
    speed: float
    optimizationType: Literal["time", "cost", "fuel"]
    restrictions: Restrictions
    model_config = ConfigDict(extra="allow")
