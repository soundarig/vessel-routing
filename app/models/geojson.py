from typing import Any

from pydantic import BaseModel, ConfigDict


class GeoJsonGeometry(BaseModel):
    type: str
    coordinates: list[float]
    model_config = ConfigDict(extra="allow")


class GeoJsonFeature(BaseModel):
    type: str = "Feature"
    geometry: GeoJsonGeometry
    properties: dict[str, Any] = {}
    model_config = ConfigDict(extra="allow")


class GeoJsonFeatureCollection(BaseModel):
    type: str = "FeatureCollection"
    features: list[GeoJsonFeature]
    model_config = ConfigDict(extra="allow")
